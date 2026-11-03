"""``[p]honeypot`` commands and the final cog class."""

import contextlib

import discord
from redbot.core import commands
from redbot.core.utils.chat_formatting import box, pagify

from .core import ChannelState, HoneypotBase, Settings, TrapChannel, Trigger
from .experiments import DESCRIPTIONS, Experiment, parse
from .names import random_name
from .templates import (
    DEFAULTS,
    VARIABLES,
    Action,
    MessageKind,
    render,
    split_images,
    validate,
)


def _parse_action(value: str) -> Action:
    aliases = {
        "kick": Action.SOFTBAN,
        "off": Action.DISABLED,
        "disable": Action.DISABLED,
    }
    try:
        return aliases.get(value.lower()) or Action(value.lower())
    except ValueError:
        msg = "Action must be `softban`, `ban` or `disabled`."
        raise commands.BadArgument(msg) from None


def _parse_kind(value: str) -> MessageKind:
    try:
        return MessageKind(value.lower())
    except ValueError:
        msg = "Message must be `warning`, `dm` or `log`."
        raise commands.BadArgument(msg) from None


def _second_slot(guild: discord.Guild) -> tuple[discord.CategoryChannel | None, int]:
    """Category and position just below the first channel everyone can post in.

    Bots aim at the first few channels but some skip the very first one, and a trap under a
    staff-looking or read-only category would be ignored or unpostable.
    """
    everyone = guild.default_role
    postable = [
        c
        for c in guild.text_channels
        if c.permissions_for(everyone).view_channel
        and c.permissions_for(everyone).send_messages
        and not c.nsfw
    ]
    postable.sort(key=lambda c: (c.category.position if c.category else -1, c.position))
    if not postable:
        return None, 0
    first = postable[0]
    return first.category, first.position + 1


class Honeypot(HoneypotBase):
    """Trap channels that kick or ban spam bots and hacked accounts the moment they post.

    Modelled on RiskyMH's Honeypot bot (honeypot.riskymh.dev): softban by default, recovery DM
    with an optional rejoin invite, per-channel counters, logs, and the same experiments.
    """

    __author__ = "Bluscream"
    __version__ = "1.0.0"

    def format_help_for_context(self, ctx: commands.Context) -> str:
        """Show the cog version in help."""
        return f"{super().format_help_for_context(ctx)}\n\nVersion: {self.__version__}"

    @commands.group(name="honeypot", aliases=["hp"], invoke_without_command=True)
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def honeypot(self, ctx: commands.GuildContext) -> None:
        """Configure honeypot channels. Without a subcommand, shows the status."""
        await self.honeypot_status(ctx)

    @honeypot.command(name="status", aliases=["settings"])
    async def honeypot_status(self, ctx: commands.GuildContext) -> None:
        """Show the settings plus a permission check."""
        settings = await self.settings(ctx.guild)
        channels = (
            ", ".join(
                f"<#{cid}> ({state.count:,})"
                for cid, state in settings.channels.items()
            )
            or "none"
        )
        experiments = (
            ", ".join(f"`{e.value}`" for e in sorted(settings.experiments)) or "none"
        )
        custom = ", ".join(k.value for k in settings.messages) or "none"
        log_channel = f"<#{settings.log_channel}>" if settings.log_channel else "none"
        text = (
            f"**Action:** {settings.action.value}\n**Channels (actions):** {channels}\n"
            f"**Log channel:** {log_channel}\n**Experiments:** {experiments}\n**Custom messages:** {custom}\n\n"
            + "\n".join(self.diagnose(ctx.guild, settings))
        )
        for page in pagify(text):
            await ctx.send(page, allowed_mentions=discord.AllowedMentions.none())

    @honeypot.command(name="add")
    async def honeypot_add(
        self, ctx: commands.GuildContext, channel: TrapChannel
    ) -> None:
        """Turn an existing (unused!) text or voice channel into a honeypot."""
        async with self.config.guild(ctx.guild).channels() as channels:
            channels.setdefault(str(channel.id), {"warning": None, "count": 0})
            self.cache_channels(ctx.guild, (int(c) for c in channels))
        await self.post_warning(channel, await self.settings(ctx.guild))
        await ctx.send(
            f"{channel.mention} is now a honeypot. Anyone who posts there is {(await self.settings(ctx.guild)).action.past_text}."
        )

    @honeypot.command(name="remove")
    async def honeypot_remove(
        self, ctx: commands.GuildContext, channel: TrapChannel
    ) -> None:
        """Stop watching a channel (its warning message is deleted)."""
        settings = await self.settings(ctx.guild)
        state = settings.channels.get(channel.id)
        if state is None:
            await ctx.send("That channel is not a honeypot.")
            return
        if state.warning_id is not None:
            self._own_deletes.add(state.warning_id)
            with contextlib.suppress(discord.HTTPException):
                await channel.get_partial_message(state.warning_id).delete()
        async with self.config.guild(ctx.guild).channels() as channels:
            channels.pop(str(channel.id), None)
            self.cache_channels(ctx.guild, (int(c) for c in channels))
        await ctx.send(f"{channel.mention} is no longer a honeypot.")

    @honeypot.command(name="create")
    async def honeypot_create(
        self, ctx: commands.GuildContext, *, name: str = ""
    ) -> None:
        """Create a new trap channel near the top of the list (second postable slot)."""
        category, position = _second_slot(ctx.guild)
        channel = await ctx.guild.create_text_channel(
            name or random_name(self._rng),
            category=category,
            position=position,
            overwrites=category.overwrites if category else {},
            reason=f"Honeypot channel created by {ctx.author}",
        )
        await self.honeypot_add(ctx, channel)

    @honeypot.command(name="action")
    async def honeypot_action(self, ctx: commands.GuildContext, action: str) -> None:
        """`softban` (default: ban + unban, cleans the last hour), `ban`, or `disabled`."""
        parsed = _parse_action(action)
        await self.config.guild(ctx.guild).action.set(parsed.value)
        await self.refresh_warnings(ctx.guild)
        await ctx.send(f"Honeypot action set to **{parsed.value}**.")

    @honeypot.command(name="logchannel", aliases=["log"])
    async def honeypot_logchannel(
        self, ctx: commands.GuildContext, channel: discord.TextChannel | None = None
    ) -> None:
        """Where actions and errors are reported. No channel clears it."""
        if channel is None:
            await self.config.guild(ctx.guild).log_channel.clear()
            await ctx.send("Log channel cleared.")
            return
        await self.config.guild(ctx.guild).log_channel.set(channel.id)
        await ctx.send(f"Honeypot logs go to {channel.mention}.")

    @honeypot.command(name="experiment", aliases=["experiments"])
    async def honeypot_experiment(
        self,
        ctx: commands.GuildContext,
        name: str = "",
        on: bool | None = None,  # noqa: FBT001 - Red converts the positional argument
    ) -> None:
        """List experiments, or turn one on/off: `[p]honeypot experiment reinvite on`."""
        settings = await self.settings(ctx.guild)
        if not name:
            lines = [
                f"[{'x' if settings.has(e) else ' '}] {e.value}: {DESCRIPTIONS[e]}"
                for e in Experiment
            ]
            for page in pagify("\n".join(lines)):
                await ctx.send(box(page))
            return
        experiment = parse(name)
        if experiment is None:
            await ctx.send(
                f"Unknown experiment `{name}`. Run `{ctx.clean_prefix}honeypot experiment` for the list."
            )
            return
        enable = not settings.has(experiment) if on is None else on
        async with self.config.guild(ctx.guild).experiments() as experiments:
            if enable and experiment.value not in experiments:
                experiments.append(experiment.value)
            elif not enable and experiment.value in experiments:
                experiments.remove(experiment.value)
        if experiment is Experiment.NO_WARNING:
            await self.refresh_warnings(ctx.guild)
        await ctx.send(f"`{experiment.value}` is now **{'on' if enable else 'off'}**.")

    @honeypot.command(name="message")
    async def honeypot_message(
        self, ctx: commands.GuildContext, kind: str, *, text: str = ""
    ) -> None:
        """Set the `warning`, `dm` or `log` text; no text restores the default.

        Image URLs on their own lines at the end become images (warning and DM, up to 4).
        See `[p]honeypot variables` for placeholders.
        """
        parsed = _parse_kind(kind)
        if text:
            problem = validate(parsed, text)
            if problem:
                await ctx.send(problem)
                return
        async with self.config.guild(ctx.guild).messages() as messages:
            if text:
                messages[parsed.value] = text
            else:
                messages.pop(parsed.value, None)
        if parsed is MessageKind.WARNING:
            await self.refresh_warnings(ctx.guild)
        await ctx.send(
            f"The {parsed.value} message was {'updated' if text else 'reset to the default'}."
        )

    @honeypot.command(name="variables")
    async def honeypot_variables(self, ctx: commands.GuildContext) -> None:
        """Placeholders each message supports."""
        lines = [
            f"{kind.value}: " + " ".join(f"{{{{{v}}}}}" for v in VARIABLES[kind])
            for kind in MessageKind
        ]
        await ctx.send(box("\n\n".join(lines)))

    @honeypot.command(name="preview")
    async def honeypot_preview(self, ctx: commands.GuildContext, kind: str) -> None:
        """Show how the `warning`, `dm` or `log` message renders, using you as the example."""
        parsed = _parse_kind(kind)
        settings = await self.settings(ctx.guild)
        if parsed is MessageKind.WARNING:
            content, embeds = self.warning_payload(ctx.guild, settings, 0)
            await ctx.send(
                content, embeds=embeds, allowed_mentions=discord.AllowedMentions.none()
            )
            return
        if parsed is MessageKind.LOG:
            channel = next(iter(settings.channels), ctx.channel.id)
            fake = Trigger(
                ctx.guild,
                ctx.channel
                if isinstance(ctx.channel, TrapChannel)
                else ctx.guild.text_channels[0],
                ctx.author,
                ctx.author,
                ctx.message,
            )
            values = self._log_values(
                fake,
                settings.action,
                settings.channels.get(channel, ChannelState()).count,
            )
            values["honeypot:channel:mention"] = f"<#{channel}>"
            await ctx.send(
                render(settings.text(MessageKind.LOG), values),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        text, images = split_images(settings.text(MessageKind.DM))
        await ctx.send(
            "DM template (variables are filled per trigger):\n"
            + box(text)
            + ("\n" + "\n".join(images) if images else ""),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @honeypot.command(name="refresh")
    async def honeypot_refresh(self, ctx: commands.GuildContext) -> None:
        """Repost or update every warning message."""
        await self.refresh_warnings(ctx.guild)
        await ctx.tick()

    @honeypot.command(name="rundaily")
    async def honeypot_rundaily(self, ctx: commands.GuildContext) -> None:
        """Run the daily experiments (warmer, rename, recreate) now."""
        settings: Settings = await self.settings(ctx.guild)
        await self.run_daily(ctx.guild, settings)
        await ctx.tick()

    @honeypot.command(name="defaults")
    async def honeypot_defaults(self, ctx: commands.GuildContext) -> None:
        """Show the built-in default texts."""
        for kind in MessageKind:
            await ctx.send(f"**{kind.value}**\n" + box(DEFAULTS[kind]))
