"""Honeypot engine: trigger detection, actions, DMs, logs, warning upkeep and daily experiments."""

import asyncio
import contextlib
import logging
import random
import re
import time
from collections.abc import Coroutine, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Self, TypeAlias

import discord
from redbot.core import Config, commands, modlog
from redbot.core.bot import Red

from .experiments import DAILY, REQUIRED_PERMISSIONS, Experiment
from .names import chaos_name, random_name
from .ratelimit import TieredLimiter
from .templates import (
    DEFAULT_DM_REINVITE,
    DEFAULTS,
    Action,
    MessageKind,
    Value,
    render,
    split_images,
)

log = logging.getLogger("red.blu.honeypot")

TrapChannel: TypeAlias = (
    discord.TextChannel | discord.VoiceChannel | discord.StageChannel
)
LogTarget: TypeAlias = TrapChannel | discord.Thread

IGNORED_TYPES = frozenset(
    {
        discord.MessageType.new_member,
        discord.MessageType.pins_add,
        discord.MessageType.premium_guild_subscription,
        discord.MessageType.premium_guild_tier_1,
        discord.MessageType.premium_guild_tier_2,
        discord.MessageType.premium_guild_tier_3,
        discord.MessageType.channel_follow_add,
        discord.MessageType.poll_result,
        discord.MessageType.purchase_notification,
        discord.MessageType.auto_moderation_action,
    }
)
FORWARDABLE = frozenset(
    {
        discord.MessageType.default,
        discord.MessageType.reply,
        discord.MessageType.chat_input_command,
        discord.MessageType.context_menu_command,
    }
)

PRE_ACTION_BUDGET = 2.0  # seconds DM/forward/timeout may run before the ban goes out
SOFTBAN_UNBAN_DELAY = 0.25
ENSURE_DELETE_DELAY = 120
ENSURE_DELETE_LOOKBACK = timedelta(minutes=10)
WARNING_EDIT_INTERVAL = 10.0
DAILY_INTERVAL = 24 * 60 * 60
DAILY_CHECK_EVERY = 15 * 60
SCAN_CHANNEL_LIMIT = 30
WARMER_TEXT = "Keeping this channel warm 🍯"


class Failure(StrEnum):
    """Why an action did not (fully) happen."""

    PERMISSIONS = "permissions"
    UNBAN = "unban"
    ERROR = "error"


class Skip(StrEnum):
    """Members the honeypot never acts on."""

    OWNER = "owner"
    ADMIN = "admin"


@dataclass(frozen=True, slots=True)
class ChannelState:
    """Per honeypot channel state."""

    warning_id: int | None = None
    count: int = 0


@dataclass(frozen=True, slots=True)
class Settings:
    """Typed view of one guild's config."""

    action: Action
    log_channel: int | None
    channels: dict[int, ChannelState]
    experiments: frozenset[Experiment]
    messages: dict[MessageKind, str]
    reinvite: str | None
    last_daily: float

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> Self:
        """Parse the stored dict, ignoring unknown experiment names from older versions."""
        known = {e.value for e in Experiment}
        return cls(
            action=Action(raw["action"]),
            log_channel=raw["log_channel"],
            channels={
                int(cid): ChannelState(state.get("warning"), int(state.get("count", 0)))
                for cid, state in raw["channels"].items()
            },
            experiments=frozenset(
                Experiment(e) for e in raw["experiments"] if e in known
            ),
            messages={MessageKind(k): v for k, v in raw["messages"].items() if v},
            reinvite=raw["reinvite"],
            last_daily=float(raw["last_daily"]),
        )

    def has(self, experiment: Experiment) -> bool:
        """Whether an experiment is on."""
        return experiment in self.experiments

    def text(self, kind: MessageKind) -> str:
        """Return the custom text, or the default."""
        return self.messages.get(kind) or DEFAULTS[kind]


@dataclass(slots=True)
class Trigger:
    """One message in a honeypot channel."""

    guild: discord.Guild
    channel: TrapChannel
    user: discord.User | discord.Member
    member: discord.Member | None
    message: discord.Message
    skip: Skip | None = field(default=None)


class UnbanButton(
    discord.ui.DynamicItem[discord.ui.Button[discord.ui.View]],
    template=r"honeypot:unban:(?P<user_id>[0-9]+)",
):
    """Persistent "Unban" button under ban log entries."""

    def __init__(self, user_id: int) -> None:
        """Build the button for one user."""
        super().__init__(
            discord.ui.Button(
                label="Unban",
                style=discord.ButtonStyle.secondary,
                custom_id=f"honeypot:unban:{user_id}",
            )
        )
        self.user_id = user_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction[discord.Client],
        item: discord.ui.Item[Any],
        match: re.Match[str],
        /,
    ) -> Self:
        """Rebuild the button after a restart."""
        del interaction, item
        return cls(int(match["user_id"]))

    async def callback(self, interaction: discord.Interaction[discord.Client]) -> None:
        """Unban, if the clicking member may ban."""
        guild = interaction.guild
        if guild is None or not interaction.permissions.ban_members:
            await interaction.response.send_message(
                "You need Ban Members to do that.", ephemeral=True
            )
            return
        try:
            await guild.unban(
                discord.Object(self.user_id),
                reason=f"Honeypot unban by {interaction.user} ({interaction.user.id})",
            )
        except discord.NotFound:
            await interaction.response.send_message(
                "That user is not banned.", ephemeral=True
            )
            return
        except discord.HTTPException as err:
            await interaction.response.send_message(
                f"Unban failed: {err}", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"Unbanned <@{self.user_id}>.", ephemeral=True
        )


def _discoverable_link(guild: discord.Guild) -> str | None:
    return (
        f"https://discord.com/servers/{guild.id}"
        if "DISCOVERABLE" in guild.features
        else None
    )


def _image_embeds(guild: discord.Guild, images: Iterable[str]) -> list[discord.Embed]:
    # Embeds sharing one URL render as a single gallery.
    url = f"https://discord.com/channels/{guild.id}"
    return [discord.Embed(url=url).set_image(url=image) for image in images]


class HoneypotBase(commands.Cog):
    """Engine shared by the command mixin."""

    def __init__(self, bot: Red) -> None:
        """Register config and in-memory state."""
        # Red's CogCommandMixin.__init__ is unannotated; untyped_calls_exclude misses super().
        super().__init__()  # type: ignore[no-untyped-call]
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=0x484F4E4559504F54, force_registration=True
        )
        self.config.register_guild(
            action=Action.SOFTBAN.value,
            log_channel=None,
            channels={},
            experiments=[],
            messages={},
            reinvite=None,
            last_daily=0.0,
        )
        self._trap_ids: dict[int, set[int]] = {}
        self._moderating: set[tuple[int, int]] = set()
        self._tasks: set[asyncio.Task[None]] = set()
        self._warning_last_edit: dict[int, float] = {}
        self._warning_pending: set[int] = set()
        self._own_deletes: set[int] = set()
        self._dm_limiter = TieredLimiter([(25, 5.0), (60, 60.0)])
        self._react_limiter = TieredLimiter([(50, 5.0), (500, 25.0)])
        self._rng = random.SystemRandom()

    # region Lifecycle

    async def cog_load(self) -> None:
        """Load the trap channel cache, the unban button and the daily loop."""
        for guild_id, raw in (await self.config.all_guilds()).items():
            self._trap_ids[guild_id] = {int(cid) for cid in raw.get("channels", {})}
        self.bot.add_dynamic_items(UnbanButton)
        self.spawn(self._daily_loop())

    async def cog_unload(self) -> None:
        """Stop background work."""
        self.bot.remove_dynamic_items(UnbanButton)
        for task in list(self._tasks):
            task.cancel()

    async def red_delete_data_for_user(self, *, requester: str, user_id: int) -> None:
        """No per-user data is stored (only per-channel counters)."""
        del requester, user_id

    def spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        """Run a background coroutine, keep a reference and log its failure."""
        task = asyncio.create_task(coro)
        self._tasks.add(task)

        def done(finished: asyncio.Task[None]) -> None:
            self._tasks.discard(finished)
            if not finished.cancelled() and (exc := finished.exception()) is not None:
                log.error("Honeypot background task failed", exc_info=exc)

        task.add_done_callback(done)

    async def settings(self, guild: discord.Guild) -> Settings:
        """Typed settings for a guild."""
        return Settings.from_raw(await self.config.guild(guild).all())

    def cache_channels(self, guild: discord.Guild, channel_ids: Iterable[int]) -> None:
        """Refresh the in-memory set used to skip non-honeypot messages cheaply."""
        self._trap_ids[guild.id] = set(channel_ids)

    # endregion Lifecycle
    # region Trigger

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Every message: cheap set lookup first, the full pipeline only for trap channels."""
        guild = message.guild
        if guild is None or message.channel.id not in self._trap_ids.get(guild.id, ()):
            return
        if not isinstance(message.channel, TrapChannel):
            return
        me = self.bot.user
        user: discord.User | discord.Member
        if (
            message.interaction_metadata is not None
            and me is not None
            and message.author.id != me.id
        ):
            # A slash command used in the trap is the invoking user's doing, not the app's.
            user = message.interaction_metadata.user
        elif (
            message.author.bot or message.author.system or message.type in IGNORED_TYPES
        ):
            return
        else:
            user = message.author
        if await self.bot.cog_disabled_in_guild(self, guild):
            return
        member = guild.get_member(user.id)
        trigger = Trigger(guild, message.channel, user, member, message)
        if user.id == guild.owner_id:
            trigger.skip = Skip.OWNER
        elif member is not None and member.guild_permissions.administrator:
            trigger.skip = Skip.ADMIN
        key = (guild.id, user.id)
        if key in self._moderating:
            return
        self._moderating.add(key)
        try:
            await self._handle(trigger)
        finally:
            self._moderating.discard(key)

    async def _handle(self, trigger: Trigger) -> None:
        settings = await self.settings(trigger.guild)
        delete_now = (
            settings.has(Experiment.ENSURE_DELETE)
            and settings.action is not Action.DISABLED
        )
        if not delete_now and self._react_limiter.try_acquire():
            self.spawn(self._react(trigger.message))
        if settings.action is Action.DISABLED:
            return
        if trigger.skip is None:
            # Forward before deleting, or the forward finds no message to reference.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    self._forward(trigger, settings), PRE_ACTION_BUDGET / 2
                )
        if delete_now:
            self.spawn(self._delete_quietly(trigger.message))

        pre = [self._dm(trigger, settings)]
        if trigger.skip is None:
            pre.append(self._timeout_first(trigger, settings))
        tasks = [asyncio.create_task(coro) for coro in pre]
        for task in tasks:
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        await asyncio.wait(tasks, timeout=PRE_ACTION_BUDGET)

        failure = None if trigger.skip else await self._execute(trigger, settings)
        count = settings.channels.get(trigger.channel.id, ChannelState()).count
        if trigger.skip is None and failure is None:
            count = await self._increment(trigger.guild, trigger.channel.id)
            await self._modlog_case(trigger, settings.action)
            if settings.has(Experiment.ENSURE_DELETE):
                self.spawn(
                    self._sweep_leftovers(
                        trigger.guild, trigger.user.id, trigger.message.created_at
                    )
                )
            self.schedule_warning_edit(trigger.guild, trigger.channel.id)
        await self._log_outcome(trigger, settings, failure, count)

    async def _execute(self, trigger: Trigger, settings: Settings) -> Failure | None:
        seconds = 900 if settings.has(Experiment.ONLY_RECENT_DELETE) else 3600
        guild, user = trigger.guild, trigger.user
        try:
            await guild.ban(
                user,
                reason=f"Triggered honeypot in #{trigger.channel.name} -> {settings.action.value}",
                delete_message_seconds=seconds,
            )
        except discord.Forbidden:
            return Failure.PERMISSIONS
        except discord.HTTPException:
            log.exception("Honeypot ban failed in %s", guild.id)
            return Failure.ERROR
        if settings.action is Action.SOFTBAN:
            await asyncio.sleep(SOFTBAN_UNBAN_DELAY)
            try:
                await guild.unban(user, reason="Triggered honeypot -> softban (unban)")
            except discord.NotFound:
                pass
            except discord.HTTPException:
                log.exception("Honeypot softban unban failed in %s", guild.id)
                return Failure.UNBAN
        return None

    async def _increment(self, guild: discord.Guild, channel_id: int) -> int:
        async with self.config.guild(guild).channels() as channels:
            entry = channels.setdefault(str(channel_id), {"warning": None, "count": 0})
            entry["count"] = int(entry.get("count", 0)) + 1
            return int(entry["count"])

    async def _modlog_case(self, trigger: Trigger, action: Action) -> None:
        me = trigger.guild.me
        try:
            await modlog.create_case(
                self.bot,
                trigger.guild,
                datetime.now(UTC),
                "softban" if action is Action.SOFTBAN else "ban",
                trigger.user,
                moderator=me,
                reason=f"Honeypot: posted in #{trigger.channel.name}",
            )
        except RuntimeError:
            # Raised when the modlog case type is disabled; the honeypot log still records it.
            log.debug("Modlog case type disabled in %s", trigger.guild.id)
        except Exception:
            # A modlog failure must not abort the rest of the trigger (DM, log, counters).
            log.exception("Honeypot modlog case failed in %s", trigger.guild.id)

    # endregion Trigger
    # region Side effects

    async def _react(self, message: discord.Message) -> None:
        with contextlib.suppress(discord.HTTPException):
            await message.add_reaction("🍯")

    async def _delete_quietly(self, message: discord.Message) -> None:
        with contextlib.suppress(discord.NotFound, discord.Forbidden):
            await message.delete()

    async def _forward(self, trigger: Trigger, settings: Settings) -> None:
        if (
            not settings.has(Experiment.FORWARD_MESSAGE)
            or trigger.message.type not in FORWARDABLE
        ):
            return
        target = self.log_channel(trigger.guild, settings)
        if target is None:
            return
        try:
            await trigger.message.forward(target)
        except discord.HTTPException as err:
            log.debug("Could not forward honeypot message: %s", err)

    async def _timeout_first(self, trigger: Trigger, settings: Settings) -> None:
        if not settings.has(Experiment.TIMEOUT_FIRST) or trigger.member is None:
            return
        with contextlib.suppress(discord.HTTPException):
            await trigger.member.timeout(
                timedelta(hours=1),
                reason=f"Triggered honeypot -> 1h timeout before {settings.action.value}",
            )

    async def build_dm_embed(
        self, trigger: Trigger, settings: Settings
    ) -> tuple[discord.Embed, list[str]]:
        """Construct a formatted rich embed with German and English sections for DMs."""
        guild = trigger.guild
        template = settings.text(MessageKind.DM)
        if (
            settings.has(Experiment.REINVITE)
            and MessageKind.DM not in settings.messages
        ):
            template += DEFAULT_DM_REINVITE
        public = _discoverable_link(guild)
        invite = ""
        if "{{reinvite:link}}" in template or settings.has(Experiment.REINVITE):
            invite = await self.reinvite_url(guild) or ""
        values: dict[str, Value] = {
            "action:text": settings.action.past_text,
            "action": settings.action.past_text,
            "server:name": guild.name,
            "server:name:linked": f"[{guild.name}]({public})" if public else guild.name,
            "server:public-link": public or "https://discord.com/servers",
            "honeypot:channel:link": trigger.message.jump_url,
            "reinvite:link": invite or "*no invite available*",
            "user:mention": trigger.user.mention,
        }
        text, images = split_images(render(template, values))

        action_en = settings.action.past_text
        action_de = {
            Action.SOFTBAN: "gekickt",
            Action.BAN: "gebannt",
            Action.DISABLED: "nicht sanktioniert",
        }.get(settings.action, action_en)

        embed = discord.Embed(
            title="🍯 Honeypot ausgelöst / Honeypot Triggered",
            color=discord.Color.red(),
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        if MessageKind.DM in settings.messages:
            embed.description = text
        else:
            de_lines = [
                f"Hallo {trigger.user.mention},",
                f"dein Account wurde auf **{guild.name}** **{action_de}**, weil dein Account in einen geschützten [Fallen-Kanal]({trigger.message.jump_url}) geschrieben hat.",
                "",
                "**Warst du das nicht?**",
                "Dein Account ist höchstwahrscheinlich kompromittiert (Session-Diebstahl, Phishing oder Malware).",
                "",
                "**Schritte zur Kontosicherheit:**",
                "1. Ändere sofort dein Discord-Passwort.",
                "2. Melde alle Sitzungen ab (*Benutzereinstellungen → Geräte*).",
                "3. Aktiviere die Zwei-Faktor-Authentifizierung (2FA).",
                "4. Entferne unbekannte Apps (*Benutzereinstellungen → Autorisierte Apps*).",
                "5. Führe einen Sicherheits-Scan deines Geräts durch.",
                "",
                "📖 [Discord-Hilfe: Gehackten Account sichern](https://dis.gd/hackedaccount)",
            ]
            embed.add_field(name="🇩🇪 Deutsch", value="\n".join(de_lines), inline=False)

            en_lines = [
                f"Hello {trigger.user.mention},",
                f"your account was **{action_en}** from **{guild.name}** for posting in a protected [trap channel]({trigger.message.jump_url}).",
                "",
                "**Was this not you?**",
                "Your account is likely compromised (stolen session token, phishing, or malware).",
                "",
                "**Security Steps:**",
                "1. Change your Discord password immediately.",
                "2. Log out of all sessions (*User Settings → Devices*).",
                "3. Enable Two-Factor Authentication (2FA).",
                "4. Revoke unauthorized apps (*User Settings → Authorized Apps*).",
                "5. Run a malware scan on your device.",
                "",
                "📖 [Discord Help: Compromised Account Guide](https://dis.gd/hackedaccount)",
            ]
            embed.add_field(name="🇬🇧 English", value="\n".join(en_lines), inline=False)

            if invite:
                embed.add_field(
                    name="🔄 Wiedereinladung / Reinvite",
                    value=f"Sobald dein Account wieder sicher ist: {invite}\nOnce your account is secured: {invite}",
                    inline=False,
                )
            else:
                embed.add_field(
                    name="🔄 Wiedereintritt / Rejoining",
                    value="Sobald dein Account wieder sicher ist, kannst du von einem bestehenden Mitglied erneut eingeladen werden.\nOnce your account is safe again, ask an existing member for a new invite.",
                    inline=False,
                )

        footer = f"Automated message sent on behalf of {guild.name}. Replies are not monitored."
        if trigger.skip:
            footer += f"\nThis is only an example: as the {trigger.skip.value} you can't be {settings.action.past_text}."
        embed.set_footer(text=footer, icon_url=guild.icon.url if guild.icon else None)

        return embed, images

    async def _dm(self, trigger: Trigger, settings: Settings) -> None:
        if settings.has(Experiment.NO_DM) or not self._dm_limiter.try_acquire():
            return
        embed, images = await self.build_dm_embed(trigger, settings)
        try:
            all_embeds = [embed, *_image_embeds(trigger.guild, images)]
            await trigger.user.send(
                embeds=all_embeds,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException as err:
            log.debug("Could not DM honeypot trigger %s: %s", trigger.user.id, err)

    def log_channel(self, guild: discord.Guild, settings: Settings) -> LogTarget | None:
        """Return the configured log channel, if it still exists and is messageable."""
        if settings.log_channel is None:
            return None
        channel = guild.get_channel_or_thread(settings.log_channel)
        if isinstance(
            channel,
            discord.TextChannel
            | discord.VoiceChannel
            | discord.StageChannel
            | discord.Thread,
        ):
            return channel
        return None

    def _log_values(
        self, trigger: Trigger, action: Action, count: int
    ) -> dict[str, Value]:
        user, member = trigger.user, trigger.member
        joined = member.joined_at if member else None
        return {
            "action:text": action.past_text,
            "action": action.past_text,
            "user": user.mention,
            "user:mention": user.mention,
            "user:id": str(user.id),
            "user:name": user.name,
            "user:global-name": user.global_name or user.name,
            "user:created": discord.utils.format_dt(user.created_at, "R"),
            "member:nickname": (member.nick if member else None) or "*none*",
            "member:joined": discord.utils.format_dt(joined, "R")
            if joined
            else "*unknown*",
            "member:roles": lambda: (
                ", ".join(r.mention for r in member.roles[1:])
                if member and len(member.roles) > 1
                else "*no roles*"
            ),
            "honeypot:channel:mention": trigger.channel.mention,
            "honeypot:moderation-count": f"{count:,}",
        }

    async def _log_outcome(
        self, trigger: Trigger, settings: Settings, failure: Failure | None, count: int
    ) -> None:
        target = self.log_channel(trigger.guild, settings)
        user = trigger.user.mention
        action = settings.action.value
        view: discord.ui.View | None = None
        if trigger.skip is not None:
            who = (
                "the **server owner**, so I can't"
                if trigger.skip is Skip.OWNER
                else "a **server admin**, so I won't"
            )
            text = (
                f"⚠️ {user} triggered the honeypot in {trigger.channel.mention}, but they are {who} {action} them.\n"
                "-# Make sure my role is above members' highest roles and that I have Ban Members, so real cases work."
            )
            target = target or trigger.channel
        elif failure is Failure.PERMISSIONS:
            text = (
                f"⚠️ {user} triggered the honeypot in {trigger.channel.mention}, but I **failed** to {action} them.\n"
                "-# Check that my role is above their highest role and that I have Ban Members (`[p]honeypot status`)."
            )
            target = target or trigger.channel
        elif failure is Failure.UNBAN:
            text = f"⚠️ {user} triggered the honeypot, but I failed to **finish** the softban: they may still be banned."
            target = target or trigger.channel
        elif failure is Failure.ERROR:
            text = f"⚠️ {user} triggered the honeypot, but the {action} failed with an unexpected Discord error."
            target = target or trigger.channel
        else:
            if target is None:
                return
            values = self._log_values(trigger, settings.action, count)
            text = render(settings.text(MessageKind.LOG), values)
            if settings.action is Action.BAN:
                view = discord.ui.View(timeout=None)
                view.add_item(UnbanButton(trigger.user.id))
        try:
            if view is None:
                await target.send(
                    text,
                    allowed_mentions=discord.AllowedMentions.none(),
                    suppress_embeds=True,
                )
            else:
                await target.send(
                    text,
                    allowed_mentions=discord.AllowedMentions.none(),
                    suppress_embeds=True,
                    view=view,
                )
        except discord.NotFound:
            if settings.log_channel is not None:
                await self.config.guild(trigger.guild).log_channel.clear()
        except discord.HTTPException as err:
            log.warning("Could not write honeypot log in %s: %s", trigger.guild.id, err)

    # endregion Side effects
    # region Ensure delete

    async def _sweep_leftovers(
        self, guild: discord.Guild, user_id: int, since: datetime
    ) -> None:
        """Discord sometimes leaves messages behind after a ban; find and delete them."""
        await asyncio.sleep(ENSURE_DELETE_DELAY)
        start = since - ENSURE_DELETE_LOOKBACK
        found = await self._search_messages(guild, user_id, start)
        if found is None:
            found = await self._scan_messages(guild, user_id, start)
        for channel_id, ids in found.items():
            channel = guild.get_channel_or_thread(channel_id)
            if not isinstance(
                channel,
                discord.TextChannel
                | discord.VoiceChannel
                | discord.StageChannel
                | discord.Thread,
            ):
                continue
            for chunk in (ids[i : i + 100] for i in range(0, len(ids), 100)):
                with contextlib.suppress(discord.HTTPException):
                    await channel.delete_messages(
                        [discord.Object(i) for i in chunk],
                        reason="Honeypot: leftover messages",
                    )
        if found:
            log.info(
                "Honeypot swept %d leftover messages in %s",
                sum(map(len, found.values())),
                guild.id,
            )

    async def _search_messages(
        self, guild: discord.Guild, user_id: int, start: datetime
    ) -> dict[int, list[int]] | None:
        route = discord.http.Route(
            "GET", "/guilds/{guild_id}/messages/search", guild_id=guild.id
        )
        found: dict[int, list[int]] = {}
        offset = 0
        while True:
            params = {
                "author_id": str(user_id),
                "min_id": str(discord.utils.time_snowflake(start)),
                "include_nsfw": "true",
                "limit": "25",
                "offset": str(offset),
            }
            try:
                data = await self.bot.http.request(route, params=params)
            except discord.HTTPException as err:
                log.debug("Message search unavailable in %s: %s", guild.id, err)
                return None
            if not isinstance(data, dict) or "messages" not in data:
                return None  # 202 "index not ready" or an unexpected shape
            for group in data["messages"]:
                for msg in group:
                    if int(msg.get("type", 0)) in {t.value for t in IGNORED_TYPES}:
                        continue
                    found.setdefault(int(msg["channel_id"]), []).append(int(msg["id"]))
            offset += 25
            if offset >= int(data.get("total_results", 0)):
                return found

    async def _scan_messages(
        self, guild: discord.Guild, user_id: int, start: datetime
    ) -> dict[int, list[int]]:
        found: dict[int, list[int]] = {}
        channels: list[discord.TextChannel | discord.VoiceChannel] = [
            *guild.text_channels,
            *guild.voice_channels,
        ]
        readable = [
            c for c in channels if c.permissions_for(guild.me).read_message_history
        ][:SCAN_CHANNEL_LIMIT]
        for channel in readable:
            with contextlib.suppress(discord.HTTPException):
                async for message in channel.history(limit=50, after=start):
                    if message.author.id == user_id:
                        found.setdefault(channel.id, []).append(message.id)
        return found

    # endregion Ensure delete
    # region Warning message

    def warning_payload(
        self, guild: discord.Guild, settings: Settings, count: int
    ) -> tuple[str, list[discord.Embed]]:
        """Content and image embeds of the channel warning."""
        values: dict[str, Value] = {
            "action:text": settings.action.future_text,
            "action": settings.action.future_text,
        }
        text, images = split_images(render(settings.text(MessageKind.WARNING), values))
        return (
            f"{text}\n\n-# 🍯 {settings.action.counter_label}: {count:,}",
            _image_embeds(guild, images),
        )

    async def post_warning(self, channel: TrapChannel, settings: Settings) -> None:
        """(Re)post the warning in a trap channel, replacing an older one."""
        state = settings.channels.get(channel.id, ChannelState())
        if state.warning_id is not None:
            self._own_deletes.add(state.warning_id)
            with contextlib.suppress(discord.HTTPException):
                await channel.get_partial_message(state.warning_id).delete()
        new_id: int | None = None
        if not settings.has(Experiment.NO_WARNING):
            content, embeds = self.warning_payload(channel.guild, settings, state.count)
            sent = await channel.send(
                content,
                embeds=embeds,
                allowed_mentions=discord.AllowedMentions.none(),
                silent=True,
            )
            new_id = sent.id
        async with self.config.guild(channel.guild).channels() as channels:
            entry = channels.setdefault(str(channel.id), {"warning": None, "count": 0})
            entry["warning"] = new_id

    def schedule_warning_edit(self, guild: discord.Guild, channel_id: int) -> None:
        """Update the counter under the warning, at most once per ``WARNING_EDIT_INTERVAL``."""
        if channel_id in self._warning_pending:
            return
        self._warning_pending.add(channel_id)
        self.spawn(self._edit_warning(guild, channel_id))

    async def _edit_warning(self, guild: discord.Guild, channel_id: int) -> None:
        try:
            wait = WARNING_EDIT_INTERVAL - (
                time.monotonic() - self._warning_last_edit.get(channel_id, 0.0)
            )
            if wait > 0:
                await asyncio.sleep(wait)
            self._warning_last_edit[channel_id] = time.monotonic()
        finally:
            self._warning_pending.discard(channel_id)
        settings = await self.settings(guild)
        state = settings.channels.get(channel_id)
        channel = guild.get_channel(channel_id)
        if (
            state is None
            or state.warning_id is None
            or not isinstance(channel, TrapChannel)
        ):
            return
        content, embeds = self.warning_payload(guild, settings, state.count)
        try:
            await channel.get_partial_message(state.warning_id).edit(
                content=content, embeds=embeds
            )
        except (discord.NotFound, discord.Forbidden):
            async with self.config.guild(guild).channels() as channels:
                if str(channel_id) in channels:
                    channels[str(channel_id)]["warning"] = None

    async def refresh_warnings(self, guild: discord.Guild) -> None:
        """Edit every warning (after an action/text change), reposting missing ones."""
        settings = await self.settings(guild)
        for channel_id, state in settings.channels.items():
            channel = guild.get_channel(channel_id)
            if not isinstance(channel, TrapChannel):
                continue
            if settings.has(Experiment.NO_WARNING) or state.warning_id is None:
                with contextlib.suppress(discord.HTTPException):
                    await self.post_warning(channel, settings)
                continue
            content, embeds = self.warning_payload(guild, settings, state.count)
            try:
                await channel.get_partial_message(state.warning_id).edit(
                    content=content, embeds=embeds
                )
            except discord.NotFound:
                with contextlib.suppress(discord.HTTPException):
                    await self.post_warning(channel, settings)
            except discord.HTTPException as err:
                log.warning(
                    "Could not refresh honeypot warning in %s: %s", channel_id, err
                )

    @commands.Cog.listener()
    async def on_raw_message_delete(
        self, payload: discord.RawMessageDeleteEvent
    ) -> None:
        """Someone deleted a warning: put it back so humans stay warned."""
        if payload.message_id in self._own_deletes:
            self._own_deletes.discard(payload.message_id)
            return
        if payload.guild_id is None or payload.channel_id not in self._trap_ids.get(
            payload.guild_id, ()
        ):
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        settings = await self.settings(guild)
        state = settings.channels.get(payload.channel_id)
        channel = guild.get_channel(payload.channel_id)
        if (
            state is None
            or state.warning_id != payload.message_id
            or not isinstance(channel, TrapChannel)
        ):
            return
        async with self.config.guild(guild).channels() as channels:
            channels[str(payload.channel_id)]["warning"] = None
        if not settings.has(Experiment.NO_WARNING):
            with contextlib.suppress(discord.HTTPException):
                await self.post_warning(channel, await self.settings(guild))

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        """Forget deleted trap or log channels."""
        guild = channel.guild
        async with self.config.guild(guild).channels() as channels:
            channels.pop(str(channel.id), None)
            self.cache_channels(guild, (int(c) for c in channels))
        if await self.config.guild(guild).log_channel() == channel.id:
            await self.config.guild(guild).log_channel.clear()

    # endregion Warning message
    # region Reinvite

    async def reinvite_url(self, guild: discord.Guild) -> str | None:
        """Return a permanent rejoin invite, reusing the stored one while it is valid."""
        code = await self.config.guild(guild).reinvite()
        if code:
            try:
                invite = await self.bot.fetch_invite(code, with_counts=False)
            except discord.NotFound:
                invite = None
            except discord.HTTPException:
                return f"https://discord.gg/{code}"
            if (
                invite is not None
                and invite.guild is not None
                and invite.guild.id == guild.id
            ):
                return invite.url
        traps = self._trap_ids.get(guild.id, set())
        everyone = guild.default_role
        candidates = [guild.rules_channel, guild.system_channel, *guild.text_channels]
        for channel in candidates:
            if channel is None or channel.id in traps:
                continue
            if (
                not channel.permissions_for(everyone).view_channel
                or not channel.permissions_for(guild.me).create_instant_invite
            ):
                continue
            try:
                invite = await channel.create_invite(
                    max_age=0, max_uses=0, unique=False, reason="Honeypot rejoin invite"
                )
            except discord.HTTPException:
                continue
            await self.config.guild(guild).reinvite.set(invite.code)
            return invite.url
        return None

    # endregion Reinvite
    # region Daily experiments

    async def _daily_loop(self) -> None:
        await self.bot.wait_until_red_ready()
        while True:
            now = time.time()
            for guild_id, raw in (await self.config.all_guilds()).items():
                guild = self.bot.get_guild(guild_id)
                if guild is None:
                    continue
                settings = Settings.from_raw(raw)
                if (
                    not settings.experiments & DAILY
                    or now - settings.last_daily < DAILY_INTERVAL
                ):
                    continue
                try:
                    await self.run_daily(guild, settings)
                except Exception:
                    # One guild's failure must not end the loop for every guild. last_daily
                    # is left untouched so the run is retried on the next check.
                    log.exception("Honeypot daily experiments failed in %s", guild_id)
                else:
                    await self.config.guild(guild).last_daily.set(now)
            await asyncio.sleep(DAILY_CHECK_EVERY)

    async def run_daily(self, guild: discord.Guild, settings: Settings) -> None:
        """Warmer, rename and recreate for every trap channel of a guild."""
        for channel_id in list(settings.channels):
            channel = guild.get_channel(channel_id)
            if not isinstance(channel, TrapChannel):
                continue
            # Voice traps keep their hand-picked name: a random text-style name would drop
            # the "do not type here" label that keeps humans out of the voice chat.
            renames = not isinstance(channel, discord.VoiceChannel)
            try:
                if settings.has(Experiment.RECREATE_CHANNEL):
                    await self._recreate(channel, settings)
                    continue
                if renames and settings.has(Experiment.RANDOM_NAME_CHAOS):
                    await channel.edit(
                        name=chaos_name(self._rng),
                        reason="Honeypot: daily random name (chaos)",
                    )
                elif renames and settings.has(Experiment.RANDOM_NAME):
                    await channel.edit(
                        name=random_name(self._rng, avoid=channel.name),
                        reason="Honeypot: daily random name",
                    )
                if settings.has(Experiment.CHANNEL_WARMER):
                    warm = await channel.send(
                        WARMER_TEXT,
                        silent=True,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                    self._own_deletes.add(warm.id)
                    await warm.delete()
            except discord.Forbidden:
                await self._log_text(
                    guild,
                    settings,
                    f"⚠️ Missing permissions for a daily honeypot experiment in {channel.mention}.",
                )
            await asyncio.sleep(1)

    async def _recreate(self, channel: TrapChannel, settings: Settings) -> None:
        guild = channel.guild
        if isinstance(channel, discord.VoiceChannel):
            name = channel.name
        elif settings.has(Experiment.RANDOM_NAME_CHAOS):
            name = chaos_name(self._rng)
        elif settings.has(Experiment.RANDOM_NAME):
            name = random_name(self._rng, avoid=channel.name)
        else:
            name = channel.name
        new = await channel.clone(name=name, reason="Honeypot: daily recreate")
        with contextlib.suppress(discord.HTTPException):
            await new.edit(position=channel.position)
        async with self.config.guild(guild).channels() as channels:
            entry = channels.pop(str(channel.id), {"warning": None, "count": 0})
            entry["warning"] = None
            channels[str(new.id)] = entry
            self.cache_channels(guild, (int(c) for c in channels))
        with contextlib.suppress(discord.HTTPException):
            await self.post_warning(new, await self.settings(guild))
        try:
            await channel.delete(reason="Honeypot: replaced by a recreated channel")
        except discord.HTTPException:
            with contextlib.suppress(discord.HTTPException):
                await channel.send(
                    f"⚠️ This channel was replaced by {new.mention} and is no longer a honeypot."
                )

    async def _log_text(
        self, guild: discord.Guild, settings: Settings, text: str
    ) -> None:
        target = self.log_channel(guild, settings)
        if target is not None:
            with contextlib.suppress(discord.HTTPException):
                await target.send(text, allowed_mentions=discord.AllowedMentions.none())

    # endregion Daily experiments
    # region Diagnostics

    def diagnose(self, guild: discord.Guild, settings: Settings) -> list[str]:
        """Everything that would stop the honeypot from working, as readable lines."""
        me = guild.me
        lines: list[str] = []
        perms = me.guild_permissions
        lines.append(
            ("✅" if perms.ban_members else "❌")
            + " Ban Members (needed for ban and softban)"
        )
        above = [
            r
            for r in guild.roles
            if r >= me.top_role and r != me.top_role and not r.managed and r.members
        ]
        risky = [r for r in above if not r.permissions.administrator]
        if risky:
            names = ", ".join(r.name for r in risky)
            lines.append(
                f"⚠️ Members with these roles are above my role and can't be actioned: {names}"
            )
        else:
            lines.append("✅ My role is above every non-admin member role")
        if not settings.channels:
            lines.append(
                "❌ No honeypot channel set (`[p]honeypot add` or `[p]honeypot create`)"
            )
        everyone = guild.default_role
        for channel_id in settings.channels:
            channel = guild.get_channel(channel_id)
            if not isinstance(channel, TrapChannel):
                lines.append(f"❌ Honeypot channel {channel_id} no longer exists")
                continue
            mine = channel.permissions_for(me)
            theirs = channel.permissions_for(everyone)
            missing = [
                name
                for name, ok in (
                    ("View Channel", mine.view_channel),
                    ("Send Messages", mine.send_messages),
                    ("Read Message History", mine.read_message_history),
                    ("Manage Messages", mine.manage_messages),
                    ("Add Reactions", mine.add_reactions),
                )
                if not ok
            ]
            status = "✅" if not missing else "⚠️"
            lines.append(
                f"{status} {channel.mention}"
                + (f": I lack {', '.join(missing)}" if missing else "")
            )
            if not (theirs.view_channel and theirs.send_messages):
                lines.append(
                    f"⚠️ {channel.mention}: @everyone can't see or post there, so spam bots can't trigger it"
                )
        target = self.log_channel(guild, settings)
        if target is None:
            lines.append(
                "⚠️ No log channel: you won't see actions or errors (`[p]honeypot logchannel`)"
            )
        elif (
            isinstance(target, discord.abc.GuildChannel)
            and not target.permissions_for(me).send_messages
        ):
            lines.append("❌ I can't send messages in the log channel")
        for experiment in sorted(settings.experiments):
            needed = [
                p
                for p in REQUIRED_PERMISSIONS.get(experiment, ())
                if not getattr(perms, p)
            ]
            if needed:
                lines.append(
                    f"⚠️ Experiment `{experiment.value}` needs: {', '.join(needed)}"
                )
        return lines

    # endregion Diagnostics
