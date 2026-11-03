"""Actions, default texts and ``{{variable}}`` rendering for the Honeypot cog (no Discord imports)."""

import re
from collections.abc import Callable, Mapping
from enum import StrEnum


class Action(StrEnum):
    """What happens to a member who posts in a honeypot channel."""

    SOFTBAN = "softban"
    BAN = "ban"
    DISABLED = "disabled"

    @property
    def future_text(self) -> str:
        """Phrase used in the channel warning ("results in …")."""
        return {
            Action.SOFTBAN: "a softban (kick + message cleanup)",
            Action.BAN: "an immediate ban",
            Action.DISABLED: "nothing right now (the honeypot is paused)",
        }[self]

    @property
    def past_text(self) -> str:
        """Phrase used in DMs and logs ("you were …")."""
        return {
            Action.SOFTBAN: "kicked",
            Action.BAN: "banned",
            Action.DISABLED: "not actioned",
        }[self]

    @property
    def counter_label(self) -> str:
        """Label of the moderation counter under the warning."""
        return {
            Action.SOFTBAN: "Kicks",
            Action.BAN: "Bans",
            Action.DISABLED: "Triggers",
        }[self]


class MessageKind(StrEnum):
    """The three customisable texts."""

    WARNING = "warning"
    DM = "dm"
    LOG = "log"


DEFAULT_WARNING = (
    "## ⚠️ Do not write in this channel\n"
    "This channel is a trap for spam bots and hacked accounts. "
    "Anything posted here results in **{{action:text}}**."
)
DEFAULT_DM = (
    "## Honeypot triggered\n"
    "Hi {{user:mention}}, you were **{{action:text}}** from **{{server:name:linked}}** because your "
    "account posted in a [trap channel]({{honeypot:channel:link}}) that members are told never to use.\n\n"
    "If that wasn't you, your account is probably compromised (stolen session token, malware or "
    "phishing). Change your password, log out of all sessions, turn on 2FA, remove authorized apps "
    "you don't recognise and scan your device. Discord's help: https://dis.gd/hackedaccount"
)
DEFAULT_DM_REINVITE = (
    "\n\nOnce your account is safe again you can rejoin: {{reinvite:link}}"
)
DEFAULT_LOG = (
    "{{user:mention}} was **{{action:text}}** for posting in {{honeypot:channel:mention}}\n"
    "-# ID `{{user:id}}` • created {{user:created}} • joined {{member:joined}}"
)

DEFAULTS: Mapping[MessageKind, str] = {
    MessageKind.WARNING: DEFAULT_WARNING,
    MessageKind.DM: DEFAULT_DM,
    MessageKind.LOG: DEFAULT_LOG,
}

LENGTH_LIMITS: Mapping[MessageKind, tuple[int, int]] = {
    MessageKind.WARNING: (25, 1500),
    MessageKind.DM: (25, 1000),
    MessageKind.LOG: (25, 500),
}

VARIABLES: Mapping[MessageKind, tuple[str, ...]] = {
    MessageKind.WARNING: ("action:text",),
    MessageKind.DM: (
        "action:text",
        "server:name",
        "server:name:linked",
        "server:public-link",
        "honeypot:channel:link",
        "reinvite:link",
        "user:mention",
    ),
    MessageKind.LOG: (
        "action:text",
        "user:mention",
        "user:id",
        "user:name",
        "user:global-name",
        "user:created",
        "member:nickname",
        "member:joined",
        "member:roles",
        "honeypot:channel:mention",
        "honeypot:moderation-count",
    ),
}

MAX_IMAGES = 4
_VARIABLE_RE = re.compile(r"\{\{([a-z:-]+)\}\}")
_IMAGE_LINE_RE = re.compile(
    r"^https://[^\s/]+\.[a-zA-Z]{2,}/\S*\.(?:png|jpe?g|gif|webp|avif)(?:[?#]\S*)?$",
    re.IGNORECASE,
)

Value = str | Callable[[], str]


def render(template: str, values: Mapping[str, Value]) -> str:
    """Replace ``{{name}}`` tokens in one pass; unknown names stay as written.

    Values may be callables so expensive ones are only computed when a template uses them.
    """

    def substitute(match: re.Match[str]) -> str:
        value = values.get(match.group(1))
        if value is None:
            return match.group(0)
        return value() if callable(value) else value

    return _VARIABLE_RE.sub(substitute, template)


def split_images(text: str) -> tuple[str, list[str]]:
    """Peel image URLs off the end of ``text`` (one per line, at most four)."""
    lines = text.rstrip().split("\n")
    images: list[str] = []
    while lines and len(images) < MAX_IMAGES:
        last = lines[-1].strip()
        if not last:
            lines.pop()
            continue
        if not _IMAGE_LINE_RE.match(last):
            break
        images.append(last)
        lines.pop()
    images.reverse()
    return "\n".join(lines).strip(), images


def validate(kind: MessageKind, text: str) -> str | None:
    """Return a human-readable problem with a custom text, or ``None`` when it is fine."""
    low, high = LENGTH_LIMITS[kind]
    if not low <= len(text) <= high:
        return f"The {kind.value} message must be {low}-{high} characters (it is {len(text)})."
    if (
        kind is MessageKind.LOG
        and "{{user:mention}}" not in text
        and "{{user:id}}" not in text
    ):
        return "The log message must contain {{user:mention}} or {{user:id}}."
    return None
