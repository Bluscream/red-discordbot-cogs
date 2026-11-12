"""VoiceChannelLog cog: posts voice activity into the voice channel's own text chat or a dedicated log channel."""

import asyncio
import datetime as dt
import logging
import time
from dataclasses import dataclass
from typing import ClassVar, TypeAlias

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box, humanize_list

from .events import (
    DEFAULT_TEMPLATES,
    EVENT_COLOURS,
    PLACEHOLDERS,
    LogMode,
    TemplateContext,
    VoiceEvent,
    detect_events,
    render,
)

log = logging.getLogger("red.blu.voicechannellog")

WEBHOOK_NAME = "VoiceChannelLog"
# Message content and webhook username length limits enforced by Discord.
MAX_CONTENT = 2000
MAX_WEBHOOK_NAME = 80

VoiceLike: TypeAlias = discord.VoiceChannel | discord.StageChannel
Target: TypeAlias = discord.TextChannel | discord.channel.VocalGuildChannel


@dataclass(frozen=True, slots=True)
class Outgoing:
    """One rendered message waiting in the send queue."""

    target: Target
    content: str | None = None
    embed: discord.Embed | None = None
    author_name: str = ""
    author_icon: str = ""


def _event_from_str(value: str) -> VoiceEvent:
    try:
        return VoiceEvent(value.lower())
    except ValueError:
        valid = humanize_list([f"`{e.value}`" for e in VoiceEvent])
        msg = f"Unknown event `{value}`. Valid events: {valid}"
        raise commands.BadArgument(msg) from None


def _mode_from_str(value: str) -> LogMode:
    val = value.strip().lower().replace("_", "-")
    match val:
        case "small" | "subtext" | "compact" | "tiny":
            return LogMode.SMALL
        case "normal" | "text" | "standard" | "default":
            return LogMode.NORMAL
        case "embed-small" | "embedsmall" | "embedd-small" | "embeddsmall" | "slim":
            return LogMode.EMBED_SMALL
        case "embed" | "embedd" | "embeds" | "rich":
            return LogMode.EMBED
        case _:
            valid = humanize_list([f"`{m.value}`" for m in LogMode])
            msg = f"Unknown mode `{value}`. Valid modes: {valid}"
            raise commands.BadArgument(msg) from None


class VoiceChannelLog(commands.Cog):
    """Log voice joins, leaves, moves, mutes, cameras and streams.

    Posts into voice text chats or a dedicated log channel with multiple formatting modes.
    """

    __author__ = "Bluscream"
    __version__ = "1.1.0"

    default_guild_settings: ClassVar[dict[str, object]] = {
        "enabled": False,
        "log_mode": "small",
        "log_channel": None,
        "voice_chat": True,
        "events": {event.value: True for event in VoiceEvent},
        "templates": {},
        "author_name": "",
        "author_icon": "",
        "ignore_bots": True,
        "ignored_channels": [],
    }

    def __init__(self, bot: Red) -> None:
        """Set up config and the send queue."""
        # Red's CogCommandMixin.__init__ is unannotated, and mypy's untyped_calls_exclude
        # does not match calls made through super().
        super().__init__()  # type: ignore[no-untyped-call]
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=896443818935713853, force_registration=True
        )
        self.config.register_guild(**self.default_guild_settings)
        self._queue: asyncio.Queue[Outgoing] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._webhooks: dict[int, discord.Webhook] = {}

    def format_help_for_context(self, ctx: commands.Context) -> str:
        """Show the cog version in help."""
        return f"{super().format_help_for_context(ctx)}\n\nVersion: {self.__version__}"

    async def red_delete_data_for_user(self, *, requester: str, user_id: int) -> None:
        """Nothing to delete: the cog stores no per-user data."""
        del requester, user_id

    async def cog_load(self) -> None:
        """Start the single send worker."""
        self._worker = asyncio.create_task(self._send_worker())

    async def cog_unload(self) -> None:
        """Stop the send worker; queued messages are dropped."""
        if self._worker is not None:
            self._worker.cancel()
            self._worker = None

    # region Sending

    async def _send_worker(self) -> None:
        """Send queued messages one at a time so ordering holds and bursts stay polite."""
        while True:
            item = await self._queue.get()
            try:
                await self._deliver(item)
            except discord.HTTPException as err:
                log.warning("Could not post voice log in %s: %s", item.target.id, err)
            except Exception:
                # Anything else must not end the worker, or voice logging stops silently.
                log.exception(
                    "Unexpected error posting voice log in %s", item.target.id
                )
            finally:
                self._queue.task_done()

    async def _deliver(self, item: Outgoing) -> None:
        mentions = discord.AllowedMentions.none()
        if item.author_name:
            webhook = await self._get_webhook(item.target)
            if webhook is not None:
                # A webhook created on a voice/stage channel posts straight into its chat.
                await webhook.send(
                    content=item.content or discord.utils.MISSING,
                    embed=item.embed or discord.utils.MISSING,
                    username=item.author_name[:MAX_WEBHOOK_NAME],
                    avatar_url=item.author_icon or discord.utils.MISSING,
                    allowed_mentions=mentions,
                )
                return
        if item.embed is not None:
            await item.target.send(
                content=item.content or discord.utils.MISSING,
                embed=item.embed,
                allowed_mentions=mentions,
            )
        elif item.content is not None:
            await item.target.send(item.content, allowed_mentions=mentions)

    async def _get_webhook(self, channel: Target) -> discord.Webhook | None:
        """Reuse or create this bot's webhook in ``channel``; ``None`` if not permitted."""
        cached = self._webhooks.get(channel.id)
        if cached is not None:
            return cached
        if not channel.permissions_for(channel.guild.me).manage_webhooks:
            log.warning(
                "Missing Manage Webhooks in %s; posting as the bot instead", channel.id
            )
            return None
        try:
            existing = await channel.webhooks()
            me = self.bot.user
            webhook = next(
                (
                    w
                    for w in existing
                    if w.name == WEBHOOK_NAME and me is not None and w.user == me
                ),
                None,
            )
            if webhook is None:
                webhook = await channel.create_webhook(
                    name=WEBHOOK_NAME, reason="VoiceChannelLog"
                )
        except discord.HTTPException as err:
            log.warning("Could not get a webhook in %s: %s", channel.id, err)
            return None
        self._webhooks[channel.id] = webhook
        return webhook

    @staticmethod
    def _build_outgoing(
        target: Target,
        event: VoiceEvent,
        rendered: str,
        context: TemplateContext,
        mode: LogMode,
        author_name: str,
        author_icon: str,
    ) -> Outgoing:
        has_embed_perm = target.permissions_for(target.guild.me).embed_links

        if mode == LogMode.SMALL:
            subtext = f"-# {rendered}" if not rendered.startswith("-#") else rendered
            return Outgoing(
                target=target,
                content=subtext[:MAX_CONTENT],
                embed=None,
                author_name=author_name,
                author_icon=author_icon,
            )

        if mode == LogMode.NORMAL or (
            mode in (LogMode.EMBED, LogMode.EMBED_SMALL) and not has_embed_perm
        ):
            return Outgoing(
                target=target,
                content=rendered[:MAX_CONTENT],
                embed=None,
                author_name=author_name,
                author_icon=author_icon,
            )

        colour = EVENT_COLOURS.get(event, 0)
        if mode == LogMode.EMBED_SMALL:
            embed = discord.Embed(
                description=rendered[:MAX_CONTENT],
                colour=colour,
            )
            return Outgoing(
                target=target,
                content=None,
                embed=embed,
                author_name=author_name,
                author_icon=author_icon,
            )

        # LogMode.EMBED
        event_dt = dt.datetime.fromtimestamp(context.timestamp, tz=dt.UTC)
        embed = discord.Embed(
            description=rendered[:MAX_CONTENT],
            colour=colour,
            timestamp=event_dt,
        )
        embed.set_author(
            name=f"{context.displayname} ({context.username})",
            icon_url=context.avatar,
        )
        return Outgoing(
            target=target,
            content=None,
            embed=embed,
            author_name=author_name,
            author_icon=author_icon,
        )

    # endregion Sending
    # region Listener

    @staticmethod
    def _associated_text_channel(voice: discord.channel.VocalGuildChannel) -> Target:
        """Same-named text channel in the same category, else the voice channel's own chat."""
        for text in voice.guild.text_channels:
            if text.name == voice.name and text.category_id == voice.category_id:
                return text
        return voice

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """Turn a voice state change into queued log messages."""
        guild = member.guild
        if await self.bot.cog_disabled_in_guild(self, guild):
            return
        settings = await self.config.guild(guild).all()
        if not settings["enabled"] or (member.bot and settings["ignore_bots"]):
            return

        ignored: set[int] = set(settings["ignored_channels"])
        log.debug("Voice update %s: %s -> %s", member.id, before, after)
        old, new = before.channel, after.channel
        now_ts = int(time.time())
        context = TemplateContext(
            username=member.name,
            displayname=member.display_name,
            userid=member.id,
            avatar=member.display_avatar.url,
            old_channel_name=old.name if old else "Unknown Channel",
            old_channel_id=old.id if old else None,
            new_channel_name=new.name if new else "Unknown Channel",
            new_channel_id=new.id if new else None,
            guild_name=guild.name,
            guild_id=guild.id,
            timestamp=now_ts,
        )
        author_name = render(settings["author_name"], context).strip()
        author_icon = render(settings["author_icon"], context).strip()

        log_channel_id = settings.get("log_channel")
        log_target: discord.TextChannel | None = None
        if log_channel_id is not None:
            ch = guild.get_channel(int(log_channel_id))
            if isinstance(ch, discord.TextChannel) and ch.permissions_for(guild.me).send_messages:
                log_target = ch

        voice_chat_enabled = bool(settings.get("voice_chat", True))
        mode = _mode_from_str(str(settings.get("log_mode", "small")))

        logged_to_channel_events: set[VoiceEvent] = set()

        for event, channel in detect_events(before, after):
            if channel.id in ignored or not settings["events"].get(event.value, True):
                continue
            template = (
                settings["templates"].get(event.value) or DEFAULT_TEMPLATES[event]
            )
            rendered = render(template, context)
            if not rendered.strip():
                continue

            # 1. Post to voice channel text chat if enabled
            if voice_chat_enabled:
                target = self._associated_text_channel(channel)
                if target.id not in ignored and target.permissions_for(guild.me).send_messages:
                    outgoing = self._build_outgoing(
                        target=target,
                        event=event,
                        rendered=rendered,
                        context=context,
                        mode=mode,
                        author_name=author_name,
                        author_icon=author_icon,
                    )
                    self._queue.put_nowait(outgoing)

            # 2. Post to central log channel if configured (deduplicate moves)
            if log_target is not None:
                if event == VoiceEvent.MOVE:
                    if VoiceEvent.MOVE in logged_to_channel_events:
                        continue
                    logged_to_channel_events.add(VoiceEvent.MOVE)

                outgoing = self._build_outgoing(
                    target=log_target,
                    event=event,
                    rendered=rendered,
                    context=context,
                    mode=mode,
                    author_name=author_name,
                    author_icon=author_icon,
                )
                self._queue.put_nowait(outgoing)

    # endregion Listener
    # region Commands

    @commands.group(name="vclog")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def vclog(self, ctx: commands.GuildContext) -> None:
        """Configure voice channel logging."""

    @vclog.command(name="enable")
    async def vclog_enable(self, ctx: commands.GuildContext) -> None:
        """Start logging voice activity in this server."""
        await self.config.guild(ctx.guild).enabled.set(True)
        await ctx.send("Voice channel logging is now **enabled**.")

    @vclog.command(name="disable")
    async def vclog_disable(self, ctx: commands.GuildContext) -> None:
        """Stop logging voice activity in this server."""
        await self.config.guild(ctx.guild).enabled.set(False)
        await ctx.send("Voice channel logging is now **disabled**.")

    @vclog.command(name="mode")
    async def vclog_mode(
        self, ctx: commands.GuildContext, mode: str | None = None
    ) -> None:
        """Set or view the voice channel log display mode.

        Modes:
        - `small`: Small, single-line Discord subtext (-#)
        - `normal`: Standard text line
        - `embed-small`: Minimal single-line embed with colored side bar
        - `embed`: Full embed with member avatar, details, and timestamp
        """
        if mode is None:
            current_str = str(await self.config.guild(ctx.guild).log_mode())
            current = _mode_from_str(current_str)
            valid = humanize_list([f"`{m.value}`" for m in LogMode])
            await ctx.send(
                f"Current voice channel log mode is **`{current.value}`**.\nAvailable modes: {valid}"
            )
            return

        parsed = _mode_from_str(mode)
        await self.config.guild(ctx.guild).log_mode.set(parsed.value)

        # Build live preview
        now_ts = int(time.time())
        sample_context = TemplateContext(
            username=ctx.author.name,
            displayname=ctx.author.display_name,
            userid=ctx.author.id,
            avatar=ctx.author.display_avatar.url,
            old_channel_name="General Voice",
            old_channel_id=ctx.channel.id,
            new_channel_name="Talks 🔊",
            new_channel_id=ctx.channel.id,
            guild_name=ctx.guild.name,
            guild_id=ctx.guild.id,
            timestamp=now_ts,
        )
        sample_rendered = render(DEFAULT_TEMPLATES[VoiceEvent.CONNECT], sample_context)
        outgoing = self._build_outgoing(
            target=ctx.channel,
            event=VoiceEvent.CONNECT,
            rendered=sample_rendered,
            context=sample_context,
            mode=parsed,
            author_name="",
            author_icon="",
        )
        header = f"Voice channel log mode set to **`{parsed.value}`**.\nPreview:"
        mentions = discord.AllowedMentions.none()
        if outgoing.embed is not None:
            await ctx.send(header, embed=outgoing.embed, allowed_mentions=mentions)
        else:
            await ctx.send(
                f"{header}\n{outgoing.content or ''}", allowed_mentions=mentions
            )

    @vclog.command(name="channel")
    async def vclog_channel(
        self, ctx: commands.GuildContext, channel: discord.TextChannel | None = None
    ) -> None:
        """Set a dedicated text channel to log voice activity to; omit channel to disable."""
        if channel is None:
            await self.config.guild(ctx.guild).log_channel.set(None)
            await ctx.send(
                "Dedicated log channel **disabled** (logging to voice chat only)."
            )
            return
        perms = channel.permissions_for(ctx.guild.me)
        if not perms.send_messages:
            await ctx.send(
                f"I don't have permission to send messages in {channel.mention}!"
            )
            return
        await self.config.guild(ctx.guild).log_channel.set(channel.id)
        await ctx.send(f"Dedicated voice logs will now be sent to {channel.mention}.")

    @vclog.command(name="voicechat")
    async def vclog_voicechat(
        self, ctx: commands.GuildContext, on: bool  # noqa: FBT001
    ) -> None:
        """Whether to post logs into each voice channel's own text chat."""
        await self.config.guild(ctx.guild).voice_chat.set(on)
        await ctx.send(
            f"Logging to voice channel text chats is now **{'enabled' if on else 'disabled'}**."
        )

    @vclog.command(name="event")
    async def vclog_event(
        self,
        ctx: commands.GuildContext,
        event: str,
        on: bool,  # noqa: FBT001 - Red converts the positional command argument
    ) -> None:
        """Turn one event type on or off. See `[p]vclog settings` for the names."""
        parsed = _event_from_str(event)
        async with self.config.guild(ctx.guild).events() as events:
            events[parsed.value] = on
        await ctx.send(f"`{parsed.value}` is now **{'on' if on else 'off'}**.")

    @vclog.command(name="template")
    async def vclog_template(
        self, ctx: commands.GuildContext, event: str, *, text: str = ""
    ) -> None:
        """Set the message for an event; leave the text empty to restore the default.

        Placeholders: {username} {displayname} {userid} {mention} {avatar}
        {oldChannelName} {oldChannelId} {newChannelName} {newChannelId}
        {guildName} {guildId} {now} {time} {relative} {date}
        """
        parsed = _event_from_str(event)
        async with self.config.guild(ctx.guild).templates() as templates:
            if text:
                templates[parsed.value] = text
            else:
                templates.pop(parsed.value, None)
        shown = text or DEFAULT_TEMPLATES[parsed]
        await ctx.send(f"`{parsed.value}` template:\n{box(shown)}")

    @vclog.command(name="author")
    async def vclog_author(self, ctx: commands.GuildContext, *, name: str = "") -> None:
        """Post through a webhook under this name (placeholders allowed); empty posts as the bot."""
        await self.config.guild(ctx.guild).author_name.set(name)
        if name:
            await ctx.send(f"Logs are posted via webhook as {box(name)}")
        else:
            await ctx.send("Logs are posted as the bot itself.")

    @vclog.command(name="icon")
    async def vclog_icon(self, ctx: commands.GuildContext, *, url: str = "") -> None:
        """Webhook avatar URL; `{avatar}` uses the member's avatar. Empty for the webhook default."""
        await self.config.guild(ctx.guild).author_icon.set(url)
        await ctx.send(f"Webhook icon set to {box(url) if url else 'the default'}")

    @vclog.command(name="ignorebots")
    async def vclog_ignorebots(self, ctx: commands.GuildContext, on: bool) -> None:  # noqa: FBT001 - Red converts the positional command argument
        """Whether bots' voice activity is skipped."""
        await self.config.guild(ctx.guild).ignore_bots.set(on)
        await ctx.send(f"Bots are now **{'ignored' if on else 'logged'}**.")

    @vclog.command(name="ignore")
    async def vclog_ignore(
        self, ctx: commands.GuildContext, channel: VoiceLike
    ) -> None:
        """Toggle whether a voice channel is excluded from logging."""
        async with self.config.guild(ctx.guild).ignored_channels() as ignored:
            if channel.id in ignored:
                ignored.remove(channel.id)
                state = "logged again"
            else:
                ignored.append(channel.id)
                state = "ignored"
        await ctx.send(f"{channel.mention} is now **{state}**.")

    @vclog.command(name="settings")
    async def vclog_settings(self, ctx: commands.GuildContext) -> None:
        """Show the current configuration."""
        settings = await self.config.guild(ctx.guild).all()
        ignored = [ctx.guild.get_channel(cid) for cid in settings["ignored_channels"]]
        log_chan_id = settings.get("log_channel")
        log_chan = ctx.guild.get_channel(int(log_chan_id)) if log_chan_id else None
        lines = [
            f"Enabled: {settings['enabled']}",
            f"Mode: {settings.get('log_mode', 'small')}",
            f"Dedicated channel: {log_chan.name if log_chan else 'none'}",
            f"Voice chat logging: {settings.get('voice_chat', True)}",
            f"Ignore bots: {settings['ignore_bots']}",
            f"Author: {settings['author_name'] or '(the bot)'}",
            f"Icon: {settings['author_icon'] or '(default)'}",
            "Ignored: "
            + (", ".join(c.name for c in ignored if c is not None) or "none"),
            "",
        ]
        for event in VoiceEvent:
            on = settings["events"].get(event.value, True)
            template = (
                settings["templates"].get(event.value) or DEFAULT_TEMPLATES[event]
            )
            lines.append(f"[{'x' if on else ' '}] {event.value}: {template}")
        lines.append("")
        lines.append("Placeholders: " + " ".join(f"{{{p}}}" for p in PLACEHOLDERS))
        for page in _paginate("\n".join(lines)):
            await ctx.send(box(page))

    # endregion Commands


def _paginate(text: str, limit: int = 1900) -> list[str]:
    pages: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > limit and current:
            pages.append(current)
            current = ""
        current += line
    if current:
        pages.append(current)
    return pages
