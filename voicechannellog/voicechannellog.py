"""VoiceChannelLog cog: posts voice activity into the voice channel's own text chat."""

import asyncio
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
    PLACEHOLDERS,
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
    content: str
    author_name: str
    author_icon: str


def _event_from_str(value: str) -> VoiceEvent:
    try:
        return VoiceEvent(value.lower())
    except ValueError:
        valid = humanize_list([f"`{e.value}`" for e in VoiceEvent])
        msg = f"Unknown event `{value}`. Valid events: {valid}"
        raise commands.BadArgument(msg) from None


class VoiceChannelLog(commands.Cog):
    """Log voice joins, leaves, moves, mutes, cameras and streams to voice text chats.

    Port of the Equicord ``voiceChannelLog`` user plugin to a server-side bot.
    """

    __author__ = "Bluscream"
    __version__ = "1.0.0"

    default_guild_settings: ClassVar[dict[str, object]] = {
        "enabled": False,
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
            finally:
                self._queue.task_done()

    async def _deliver(self, item: Outgoing) -> None:
        mentions = discord.AllowedMentions.none()
        if item.author_name:
            webhook = await self._get_webhook(item.target)
            if webhook is not None:
                # A webhook created on a voice/stage channel posts straight into its chat.
                await webhook.send(
                    item.content,
                    username=item.author_name[:MAX_WEBHOOK_NAME],
                    avatar_url=item.author_icon or discord.utils.MISSING,
                    allowed_mentions=mentions,
                )
                return
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
            now=f"<t:{int(time.time())}:f>",
        )
        author_name = render(settings["author_name"], context).strip()
        author_icon = render(settings["author_icon"], context).strip()

        for event, channel in detect_events(before, after):
            if channel.id in ignored or not settings["events"].get(event.value, True):
                continue
            template = (
                settings["templates"].get(event.value) or DEFAULT_TEMPLATES[event]
            )
            content = render(template, context)[:MAX_CONTENT]
            if not content.strip():
                continue
            target = self._associated_text_channel(channel)
            if not target.permissions_for(guild.me).send_messages:
                log.debug("No send permission in %s, skipping %s", target.id, event)
                continue
            self._queue.put_nowait(Outgoing(target, content, author_name, author_icon))

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

        Placeholders: {username} {displayname} {userid} {avatar} {oldChannelName}
        {oldChannelId} {newChannelName} {newChannelId} {guildName} {guildId} {now}
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
        lines = [
            f"Enabled: {settings['enabled']}",
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
