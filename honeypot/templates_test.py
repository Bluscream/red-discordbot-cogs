"""Tests for honeypot templates, names, experiments and the rate limiter."""

import random

from .experiments import DESCRIPTIONS, Experiment, parse
from .names import NAMES, chaos_name, random_name
from .ratelimit import TieredLimiter
from .templates import (
    DEFAULTS,
    VARIABLES,
    Action,
    MessageKind,
    render,
    split_images,
    validate,
)


def test_render_known_unknown_and_lazy() -> None:
    calls: list[int] = []

    def lazy() -> str:
        calls.append(1)
        return "L"

    assert render("{{a}} {{b}} {{lazy}}", {"a": "x", "lazy": lazy}) == "x {{b}} L"
    assert calls == [1]
    assert render("{{a}}", {"a": "{{a}}"}) == "{{a}}"  # single pass, no re-expansion


def test_lazy_value_not_called_when_unused() -> None:
    def boom() -> str:
        raise AssertionError

    assert render("plain", {"x": boom}) == "plain"


def test_split_images() -> None:
    text = "Hello\nworld\n\nhttps://a.example.com/x.png\nhttps://b.example.com/y.JPG?size=2\n"
    body, images = split_images(text)
    assert body == "Hello\nworld"
    assert images == [
        "https://a.example.com/x.png",
        "https://b.example.com/y.JPG?size=2",
    ]


def test_split_images_caps_at_four_and_ignores_middle_urls() -> None:
    urls = [f"https://c.example.com/{i}.png" for i in range(6)]
    body, images = split_images(
        "intro https://c.example.com/in.png\n" + "\n".join(urls)
    )
    assert images == urls[2:]
    assert body.startswith("intro https://c.example.com/in.png")


def test_validate() -> None:
    assert validate(MessageKind.LOG, "x" * 30) is not None  # needs a user placeholder
    assert validate(MessageKind.LOG, "{{user:mention}} got caught, sorry") is None
    assert validate(MessageKind.WARNING, "short") is not None
    assert validate(MessageKind.DM, "y" * 1001) is not None


def test_defaults_are_valid_and_only_use_known_variables() -> None:
    for kind, text in DEFAULTS.items():
        assert validate(kind, text) is None, kind
        rendered = render(text, dict.fromkeys(VARIABLES[kind], "v"))
        assert "{{" not in rendered, kind


def test_action_texts() -> None:
    assert Action.SOFTBAN.past_text == "kicked"
    assert Action.BAN.counter_label == "Bans"
    assert all(a.future_text for a in Action)


def test_experiments_parse_and_describe() -> None:
    assert parse("Forward_Message") is Experiment.FORWARD_MESSAGE
    assert parse("random channel name") is Experiment.RANDOM_NAME
    assert parse("nope") is None
    assert set(DESCRIPTIONS) == set(Experiment)


DISCORD_CHANNEL_NAME_MAX = 100
CHAOS_NAME_MAX = 26


def test_names() -> None:
    rng = random.Random(1)  # noqa: S311 - seeded for reproducible tests, not security
    assert all(
        n == n.lower() and " " not in n and len(n) <= DISCORD_CHANNEL_NAME_MAX
        for n in NAMES
    )
    assert len(set(NAMES)) == len(NAMES)
    for _ in range(50):
        assert random_name(rng, avoid=NAMES[0]) != NAMES[0]
        name = chaos_name(rng)
        assert 1 <= len(name) <= CHAOS_NAME_MAX
        assert not name.startswith("-")


def test_tiered_limiter() -> None:
    now = [0.0]
    limiter = TieredLimiter([(2, 5.0), (3, 60.0)], clock=lambda: now[0])
    assert limiter.try_acquire()
    assert limiter.try_acquire()
    assert not limiter.try_acquire()  # 2 per 5s
    now[0] = 5.0
    assert limiter.try_acquire()
    assert not limiter.try_acquire()  # 3 per 60s
    now[0] = 61.0
    assert limiter.try_acquire()
