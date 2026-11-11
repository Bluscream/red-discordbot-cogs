"""Tests for the scam softban checks."""

from dataclasses import replace

from .scam import Roles, clip, refusal

BASE = Roles(
    actor_id=1,
    actor_top=10,
    target_id=2,
    target_top=5,
    bot_id=3,
    bot_top=20,
    owner_id=4,
)


def test_clip() -> None:
    assert clip("abc", 3) == "abc"
    assert clip("abcd", 3) == "ab…"


def test_allowed_below_actor_and_bot() -> None:
    assert refusal(BASE) is None


def test_non_member_target_is_allowed() -> None:
    assert refusal(replace(BASE, target_top=None)) is None


def test_refuses_self_bot_and_owner() -> None:
    assert refusal(replace(BASE, target_id=1)) is not None
    assert refusal(replace(BASE, target_id=3)) is not None
    assert refusal(replace(BASE, target_id=4)) is not None


def test_refuses_equal_or_higher_than_actor() -> None:
    assert refusal(replace(BASE, target_top=10)) is not None
    assert refusal(replace(BASE, target_top=15)) is not None


def test_owner_and_bot_owner_skip_actor_hierarchy() -> None:
    high = replace(BASE, target_top=15)
    assert refusal(replace(high, actor_id=4)) is None
    assert refusal(replace(high, actor_is_bot_owner=True)) is None


def test_bot_hierarchy_always_applies() -> None:
    above_bot = replace(BASE, target_top=20, actor_is_bot_owner=True)
    assert refusal(above_bot) is not None
