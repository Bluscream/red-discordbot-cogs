"""Tests for the pure voice-state diff and template rendering."""

from dataclasses import dataclass

from .events import (
    DEFAULT_TEMPLATES,
    EVENT_COLOURS,
    LogMode,
    TemplateContext,
    VoiceEvent,
    detect_events,
    render,
)


@dataclass(frozen=True)
class Chan:
    id: int


@dataclass(frozen=True)
class State:
    channel: Chan | None = None
    self_mute: bool = False
    self_deaf: bool = False
    self_video: bool = False
    self_stream: bool | None = False
    mute: bool = False
    deaf: bool = False


A, B = Chan(1), Chan(2)


def test_connect() -> None:
    assert detect_events(State(), State(A)) == [(VoiceEvent.CONNECT, A)]


def test_connect_while_muted_reports_no_toggle() -> None:
    assert detect_events(State(), State(A, self_mute=True)) == [(VoiceEvent.CONNECT, A)]


def test_disconnect_reported_in_old_channel() -> None:
    assert detect_events(State(A), State()) == [(VoiceEvent.DISCONNECT, A)]


def test_move_reported_in_both_channels() -> None:
    assert detect_events(State(A), State(B)) == [
        (VoiceEvent.MOVE, A),
        (VoiceEvent.MOVE, B),
    ]


def test_self_toggles() -> None:
    before = State(A)
    cases = [
        (State(A, self_mute=True), VoiceEvent.MUTE, VoiceEvent.UNMUTE),
        (State(A, self_deaf=True), VoiceEvent.DEAFEN, VoiceEvent.UNDEAFEN),
        (State(A, self_video=True), VoiceEvent.CAMERA_ON, VoiceEvent.CAMERA_OFF),
        (State(A, self_stream=True), VoiceEvent.STREAM_START, VoiceEvent.STREAM_STOP),
        (State(A, mute=True), VoiceEvent.SERVER_MUTE, VoiceEvent.SERVER_UNMUTE),
        (State(A, deaf=True), VoiceEvent.SERVER_DEAFEN, VoiceEvent.SERVER_UNDEAFEN),
    ]
    for after, on, off in cases:
        assert detect_events(before, after) == [(on, A)], on
        assert detect_events(after, before) == [(off, A)], off


def test_server_mute_suppressed_when_self_mute_changes_too() -> None:
    assert detect_events(State(A), State(A, self_mute=True, mute=True)) == [
        (VoiceEvent.MUTE, A)
    ]


def test_stream_none_counts_as_off() -> None:
    assert detect_events(State(A, self_stream=None), State(A)) == []


def test_no_change() -> None:
    assert detect_events(State(A), State(A)) == []


CTX = TemplateContext(
    username="blu",
    displayname="{userid} b1u",
    userid=42,
    avatar="https://cdn/a.png",
    old_channel_name="Unknown Channel",
    old_channel_id=None,
    new_channel_name="yapyap",
    new_channel_id=7,
    guild_name="G",
    guild_id=9,
    timestamp=1731410870,
)


def test_render_default_connect() -> None:
    assert (
        render(DEFAULT_TEMPLATES[VoiceEvent.CONNECT], CTX)
        == "🟢 <t:1731410870:T> **{userid} b1u** joined <#7>"
    )


def test_render_placeholders() -> None:
    template = "{time} | {now} | {relative} | {date} | {mention} | {displayname} | {username}"
    expected = (
        "<t:1731410870:T> | <t:1731410870:f> | <t:1731410870:R> | <t:1731410870:d> | "
        "<@42> | {userid} b1u | blu"
    )
    assert render(template, CTX) == expected


def test_render_is_single_pass_and_keeps_unknown() -> None:
    assert render("{displayname} {oldChannelId}|{nope}", CTX) == "{userid} b1u |{nope}"


def test_every_event_has_a_default_template() -> None:
    assert set(DEFAULT_TEMPLATES) == set(VoiceEvent)


def test_every_event_has_a_colour() -> None:
    assert set(EVENT_COLOURS) == set(VoiceEvent)


def test_log_modes_exist() -> None:
    assert {m.value for m in LogMode} == {"small", "normal", "embed-small", "embed"}
