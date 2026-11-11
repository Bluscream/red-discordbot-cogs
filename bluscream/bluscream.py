"""Bluscream cog for Red-DiscordBot: scam softbans and small utility commands."""

from __future__ import annotations

import io
import logging
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands
from redbot.core import Config, commands
from redbot.core.utils.chat_formatting import box, error, success

from .scam import Request, Roles, refusal, softban, target_problem

if TYPE_CHECKING:
    from discord.ext.commands import Command as DpyCommand
    from redbot.core.bot import Red

log = logging.getLogger("red.blu.bluscream")

# Guild and channel the scam report was hardcoded to before it became a setting.
LEGACY_REPORT = (747967102895390741, 896433099100016750)
# Servers where scam bans exist at all (prefix command and context menu); Flat2VR Modding.
DEFAULT_SCAM_GUILDS = [747967102895390741]
SCHEMA_VERSION = 2
INLINE_DUMP_MAX = 1900  # leaves room for the note and code fence under Discord's 2000


async def _scam_here(ctx: commands.Context) -> bool:
    """Command check: hide and block the scam commands outside the allowlisted servers."""
    cog = ctx.cog
    return isinstance(cog, Bluscream) and await cog.scam_allowed(ctx.guild)


class Bluscream(commands.Cog):
    """Scam softbans and small utility commands."""

    __author__ = "Bluscream"
    __version__ = "2.0.0"

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=928374561, force_registration=True
        )
        self.config.register_global(schema_version=1, scam_guilds=DEFAULT_SCAM_GUILDS)
        self.config.register_guild(scam_channel=None)
        self.scam_menu = app_commands.ContextMenu(
            name="Scam ban", callback=self.scam_menu_cb
        )
        self.scam_menu.default_permissions = discord.Permissions(ban_members=True)
        self.scam_menu.guild_only = True
        self._menu_guilds: list[int] = []

    async def cog_load(self) -> None:
        """Migrate settings and register the message context menu."""
        if await self.config.schema_version() < SCHEMA_VERSION:
            guild_id, channel_id = LEGACY_REPORT
            await self.config.guild_from_id(guild_id).scam_channel.set(channel_id)
            await self.config.schema_version.set(SCHEMA_VERSION)
        self._register_menu(await self.config.scam_guilds())

    async def cog_unload(self) -> None:
        """Remove the context menu again."""
        self._register_menu([])

    def _register_menu(self, guild_ids: list[int]) -> None:
        """Register the context menu for exactly these guilds (guild-scoped, never global).

        Guild-scoped commands bypass Red's `[p]slash enable`; they appear after
        `[p]slash sync <guild>`.
        """
        for guild_id in self._menu_guilds:
            self.bot.tree.remove_command(
                self.scam_menu.name,
                guild=discord.Object(guild_id),
                type=self.scam_menu.type,
            )
        if guild_ids:
            self.bot.tree.add_command(
                self.scam_menu,
                guilds=[discord.Object(g) for g in guild_ids],
                override=True,
            )
        self._menu_guilds = list(guild_ids)

    async def scam_allowed(self, guild: discord.Guild | None) -> bool:
        """Whether scam bans are enabled in this guild."""
        return guild is not None and guild.id in await self.config.scam_guilds()

    async def red_delete_data_for_user(self, *, requester: str, user_id: int) -> None:
        """No per-user data is stored."""
        del requester, user_id

    # region Scam

    async def _report_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        channel = guild.get_channel(await self.config.guild(guild).scam_channel() or 0)
        return channel if isinstance(channel, discord.TextChannel) else None

    async def _check(
        self, actor: discord.Member, message: discord.Message
    ) -> str | None:
        """Return why `actor` may not scam-ban the author of `message`, or None."""
        problem = target_problem(message)
        if problem is not None:
            return problem
        guild = actor.guild
        target = message.author
        member = (
            target
            if isinstance(target, discord.Member)
            else guild.get_member(target.id)
        )
        return refusal(
            Roles(
                actor_id=actor.id,
                actor_top=actor.top_role.position,
                target_id=target.id,
                target_top=member.top_role.position if member else None,
                bot_id=guild.me.id,
                bot_top=guild.me.top_role.position,
                owner_id=guild.owner_id or 0,
                actor_is_bot_owner=await self.bot.is_owner(actor),
            )
        )

    async def _run(
        self, actor: discord.Member, message: discord.Message, reason: str
    ) -> str:
        """Check, softban and report; return the line to show the moderator."""
        problem = await self._check(actor, message)
        if problem is not None:
            return error(problem)
        request = Request(
            guild=actor.guild,
            actor=actor,
            message=message,
            reason=reason or f"Scam in #{getattr(message.channel, 'name', '?')}",
            report_channel=await self._report_channel(actor.guild),
        )
        try:
            return success(await softban(self.bot, request))
        except discord.Forbidden:
            return error(
                "I'm missing the Ban Members permission or my role is too low."
            )
        except discord.HTTPException as exc:
            log.exception("Scam softban failed in %s", actor.guild.id)
            return error(f"Discord rejected the softban: {exc.text or exc.status}")

    @commands.group(name="scam", invoke_without_command=True)
    @commands.guild_only()
    @commands.check(_scam_here)
    @commands.admin_or_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def scam(self, ctx: commands.GuildContext, *, reason: str = "") -> None:
        """Reply to a scam message with this to softban its author.

        Bans with a 7-day message purge and unbans right away. The message text and
        attachments are saved to the report channel first (`[p]scam channel`).
        You can also right-click the message: Apps → Scam ban.
        """
        ref = ctx.message.reference
        target = ref.resolved if ref else None
        if ref and ref.message_id and not isinstance(target, discord.Message):
            try:
                target = await ctx.channel.fetch_message(ref.message_id)
            except discord.NotFound:
                target = None
        if not isinstance(target, discord.Message):
            await ctx.send(error("Reply to the scam message with this command."))
            return
        result = await self._run(ctx.author, target, reason)
        await ctx.send(result, delete_after=15)
        if ctx.channel.permissions_for(ctx.me).manage_messages:
            try:
                await ctx.message.delete()
            except discord.HTTPException:
                log.debug("Could not delete the scam command message")

    @scam.command(name="channel")
    async def scam_channel(
        self, ctx: commands.GuildContext, channel: discord.TextChannel | None = None
    ) -> None:
        """Set the channel scam reports go to; leave empty to turn reports off."""
        await self.config.guild(ctx.guild).scam_channel.set(
            channel.id if channel else None
        )
        if channel:
            await ctx.send(success(f"Scam reports now go to {channel.mention}."))
        else:
            await ctx.send(success("Scam reports are off."))

    async def scam_menu_cb(
        self, interaction: discord.Interaction, message: discord.Message
    ) -> None:
        """Apps → Scam ban on a message."""
        actor = interaction.user
        if not await self.scam_allowed(interaction.guild):
            await interaction.response.send_message(
                error("Scam bans are not enabled on this server."), ephemeral=True
            )
            return
        if not isinstance(actor, discord.Member) or not (
            actor.guild_permissions.ban_members or await self.bot.is_owner(actor)
        ):
            await interaction.response.send_message(
                error("You need the Ban Members permission."), ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await interaction.followup.send(
            await self._run(actor, message, ""), ephemeral=True
        )

    # endregion Scam
    # region Utilities

    @commands.group(name="bluscream", aliases=["blu"], invoke_without_command=True)
    async def bluscream(self, ctx: commands.Context) -> None:
        """Bluscream utility commands."""
        await ctx.send_help(ctx.command)

    @bluscream.command(name="dumpcmds")
    @commands.is_owner()
    async def dumpcmds(self, ctx: commands.Context) -> None:
        """Dump all commands as CSV: cog;command;aliases;arguments."""
        rows = sorted(
            (
                (
                    cmd.cog_name or "No Cog",
                    cmd.qualified_name,
                    ",".join(cmd.aliases),
                    _signature(cmd),
                )
                for cmd in self.bot.walk_commands()
            ),
            key=lambda row: (row[0], row[1]),
        )
        lines = ["cog;command;comma_separated_aliases;arguments"]
        lines += [";".join(field.replace(";", "\\;") for field in row) for row in rows]
        content = "\n".join(lines)
        note = success(f"Generated command dump with {len(rows)} commands.")
        if len(content) > INLINE_DUMP_MAX:
            await ctx.send(
                note,
                file=discord.File(io.BytesIO(content.encode()), "commands_dump.csv"),
            )
        else:
            await ctx.send(f"{note}\n{box(content, lang='csv')}")

    @bluscream.command(name="scamguilds")
    @commands.is_owner()
    async def scamguilds(self, ctx: commands.Context, *guild_ids: int) -> None:
        """Show or set the server IDs where scam bans exist; none given shows them."""
        if guild_ids:
            await self.config.scam_guilds.set(list(guild_ids))
            self._register_menu(list(guild_ids))
        current = await self.config.scam_guilds()
        names = [
            f"{g.name} (`{g.id}`)"
            if (g := self.bot.get_guild(i))
            else f"`{i}` (bot not in it)"
            for i in current
        ]
        note = (
            f"\nRun `{ctx.clean_prefix}slash sync <guild>` for each changed server."
            if guild_ids
            else ""
        )
        await ctx.send(
            f"Scam bans are enabled in: {', '.join(names) or 'nowhere'}{note}"
        )

    @commands.group(name="role")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_roles=True)
    async def role(self, ctx: commands.GuildContext) -> None:
        """Role management commands."""

    @role.command(name="add")
    @commands.bot_has_permissions(manage_roles=True)
    async def role_add(
        self, ctx: commands.GuildContext, name: str, color: discord.Color | None = None
    ) -> None:
        """Create a role without permissions at the bottom of the list (random colour if omitted)."""
        new_role = await ctx.guild.create_role(
            name=name,
            color=color or discord.Color.random(),
            permissions=discord.Permissions.none(),
            reason=f"Created by {ctx.author} ({ctx.author.id}) via bluscream cog",
        )
        await new_role.edit(position=1)
        await ctx.send(success(f"Role **{name}** created at the bottom of the list."))

    @commands.Cog.listener()
    async def on_command(self, ctx: commands.Context) -> None:
        """Log command use at debug level (large servers make INFO too noisy)."""
        log.debug(
            "Command %s by %s in %s/%s",
            ctx.command,
            ctx.author.id,
            ctx.guild.id if ctx.guild else "DM",
            ctx.channel.id,
        )

    # endregion Utilities


def _signature(command: DpyCommand[Any, ..., Any]) -> str:
    """Render a command's parameters as `<required>` / `[optional]`."""
    parts = []
    for name, param in command.clean_params.items():
        dots = "..." if param.kind is param.VAR_POSITIONAL else ""
        parts.append(
            f"<{name}{dots}>" if param.default is param.empty else f"[{name}{dots}]"
        )
    return " ".join(parts)
