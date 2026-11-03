"""Pure voice-state diffing and template rendering for the VoiceChannelLog cog.

Nothing in here touches Discord. The cog feeds ``discord.VoiceState`` objects in through the
structural protocols below, which keeps this module testable without a gateway.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, TypeVar


class VoiceEvent(StrEnum):
    """Every voice event the cog can report."""

    CONNECT = "connect"
    DISCONNECT = "disconnect"
    MOVE = "move"
    MUTE = "mute"
    UNMUTE = "unmute"
    DEAFEN = "deafen"
    UNDEAFEN = "undeafen"
    CAMERA_ON = "camera_on"
    CAMERA_OFF = "camera_off"
    STREAM_START = "stream_start"
    STREAM_STOP = "stream_stop"
    SERVER_MUTE = "server_mute"
    SERVER_UNMUTE = "server_unmute"
    SERVER_DEAFEN = "server_deafen"
    SERVER_UNDEAFEN = "server_undeafen"


DEFAULT_TEMPLATES: Mapping[VoiceEvent, str] = {
    VoiceEvent.CONNECT: "🔊 <@{userid}> connected to <#{newChannelId}>",
    VoiceEvent.DISCONNECT: "🔇 <@{userid}> disconnected from <#{oldChannelId}>",
    VoiceEvent.MOVE: "🔄 <@{userid}> moved to <#{newChannelId}>",
    VoiceEvent.MUTE: "🔇 <@{userid}> muted themselves",
    VoiceEvent.UNMUTE: "🔊 <@{userid}> unmuted themselves",
    VoiceEvent.DEAFEN: "🤐 <@{userid}> deafened themselves",
    VoiceEvent.UNDEAFEN: "👂 <@{userid}> undeafened themselves",
    VoiceEvent.CAMERA_ON: "📹 <@{userid}> enabled their camera",
    VoiceEvent.CAMERA_OFF: "📴 <@{userid}> disabled their camera",
    VoiceEvent.STREAM_START: "📺 <@{userid}> started streaming",
    VoiceEvent.STREAM_STOP: "⏹️ <@{userid}> stopped streaming",
    VoiceEvent.SERVER_MUTE: "🔇 <@{userid}> was muted by server/admin",
    VoiceEvent.SERVER_UNMUTE: "🔊 <@{userid}> was unmuted by server/admin",
    VoiceEvent.SERVER_DEAFEN: "🤐 <@{userid}> was deafened by server/admin",
    VoiceEvent.SERVER_UNDEAFEN: "👂 <@{userid}> was undeafened by server/admin",
}

PLACEHOLDERS: tuple[str, ...] = (
    "username",
    "displayname",
    "userid",
    "avatar",
    "oldChannelName",
    "oldChannelId",
    "newChannelName",
    "newChannelId",
    "guildName",
    "guildId",
    "now",
)

_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


class ChannelLike(Protocol):
    """The part of a voice channel the diff needs: its identity."""

    @property
    def id(self) -> int:
        """Snowflake of the channel."""
        ...


ChannelT = TypeVar("ChannelT", bound=ChannelLike)
ChannelT_co = TypeVar("ChannelT_co", bound=ChannelLike, covariant=True)


class VoiceStateLike(Protocol[ChannelT_co]):
    """Structural view of ``discord.VoiceState``."""

    @property
    def channel(self) -> ChannelT_co | None:
        """Channel the member is in, or ``None`` when not connected."""
        ...

    @property
    def self_mute(self) -> bool:
        """Whether the member muted themselves."""
        ...

    @property
    def self_deaf(self) -> bool:
        """Whether the member deafened themselves."""
        ...

    @property
    def self_video(self) -> bool:
        """Whether the member's camera is on."""
        ...

    @property
    def self_stream(self) -> bool | None:
        """Whether the member is streaming (Go Live)."""
        ...

    @property
    def mute(self) -> bool:
        """Whether the member is server-muted."""
        ...

    @property
    def deaf(self) -> bool:
        """Whether the member is server-deafened."""
        ...


def _toggle(
    *, was: bool, now: bool, on: VoiceEvent, off: VoiceEvent
) -> VoiceEvent | None:
    if was == now:
        return None
    return on if now else off


def detect_events(
    before: VoiceStateLike[ChannelT], after: VoiceStateLike[ChannelT]
) -> list[tuple[VoiceEvent, ChannelT]]:
    """Return every event between two voice states, each with the channel to report it in.

    Mirrors the Equicord plugin: state toggles are only reported while the member stays
    connected (a fresh connect carries no "previous state"), server mute/deafen is only
    reported when the matching self flag did not change at the same time, and a move is
    reported in both the old and the new channel.
    """
    old, new = before.channel, after.channel
    events: list[tuple[VoiceEvent, ChannelT]] = []

    if old is not None and new is not None:
        toggles = [
            _toggle(
                was=before.self_mute,
                now=after.self_mute,
                on=VoiceEvent.MUTE,
                off=VoiceEvent.UNMUTE,
            ),
            _toggle(
                was=before.self_deaf,
                now=after.self_deaf,
                on=VoiceEvent.DEAFEN,
                off=VoiceEvent.UNDEAFEN,
            ),
            _toggle(
                was=before.self_video,
                now=after.self_video,
                on=VoiceEvent.CAMERA_ON,
                off=VoiceEvent.CAMERA_OFF,
            ),
            _toggle(
                was=bool(before.self_stream),
                now=bool(after.self_stream),
                on=VoiceEvent.STREAM_START,
                off=VoiceEvent.STREAM_STOP,
            ),
        ]
        if before.self_mute == after.self_mute:
            toggles.append(
                _toggle(
                    was=before.mute,
                    now=after.mute,
                    on=VoiceEvent.SERVER_MUTE,
                    off=VoiceEvent.SERVER_UNMUTE,
                )
            )
        if before.self_deaf == after.self_deaf:
            toggles.append(
                _toggle(
                    was=before.deaf,
                    now=after.deaf,
                    on=VoiceEvent.SERVER_DEAFEN,
                    off=VoiceEvent.SERVER_UNDEAFEN,
                )
            )
        events.extend((event, new) for event in toggles if event is not None)

    if old is None and new is not None:
        events.append((VoiceEvent.CONNECT, new))
    elif old is not None and new is None:
        events.append((VoiceEvent.DISCONNECT, old))
    elif old is not None and new is not None and old.id != new.id:
        events.append((VoiceEvent.MOVE, old))
        events.append((VoiceEvent.MOVE, new))

    return events


@dataclass(frozen=True, slots=True)
class TemplateContext:
    """Values for every placeholder a template may use."""

    username: str
    displayname: str
    userid: int
    avatar: str
    old_channel_name: str
    old_channel_id: int | None
    new_channel_name: str
    new_channel_id: int | None
    guild_name: str
    guild_id: int
    now: str

    def as_mapping(self) -> dict[str, str]:
        """Return the placeholder name to value mapping."""

        def snowflake(value: int | None) -> str:
            return "" if value is None else str(value)

        return {
            "username": self.username,
            "displayname": self.displayname,
            "userid": str(self.userid),
            "avatar": self.avatar,
            "oldChannelName": self.old_channel_name,
            "oldChannelId": snowflake(self.old_channel_id),
            "newChannelName": self.new_channel_name,
            "newChannelId": snowflake(self.new_channel_id),
            "guildName": self.guild_name,
            "guildId": str(self.guild_id),
            "now": self.now,
        }


def render(template: str, context: TemplateContext) -> str:
    """Fill ``{placeholder}`` tokens in a single pass; unknown tokens are left untouched.

    A single pass matters: a display name that itself contains ``{userid}`` must not be
    expanded a second time.
    """
    values = context.as_mapping()
    return _PLACEHOLDER_RE.sub(
        lambda match: values.get(match.group(1), match.group(0)), template
    )
