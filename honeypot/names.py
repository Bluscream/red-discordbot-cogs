"""Channel names for the daily rename / recreate experiments.

The names are deliberately honest for humans ("do not type here") while varying daily, so a
spam tool cannot keep a blacklist of honeypot channel names.
"""

import random
import string

NAMES: tuple[str, ...] = (
    "do-not-type-here",
    "dont-write-here",
    "keep-this-empty",
    "no-messages-please",
    "stay-quiet-here",
    "silent-zone",
    "read-only-please",
    "please-dont-post",
    "nothing-to-see",
    "leave-it-blank",
    "hands-off",
    "no-chat-zone",
    "empty-on-purpose",
    "dont-post-here",
    "not-a-chat",
    "quiet-corner",
    "no-typing",
    "keep-scrolling",
    "do-not-reply",
    "skip-this-one",
    "no-posting",
    "stay-out",
    "this-stays-empty",
    "just-look",
    "look-dont-type",
    "posting-disabled",
    "do-not-use",
    "no-text-here",
    "blank-channel",
    "dont-touch",
    "nicht-schreiben",
    "bitte-leer-lassen",
    "hier-nicht-tippen",
    "kein-chat-hier",
    "finger-weg",
    "nur-lesen",
    "leerer-kanal",
    "nichts-posten",
    "bitte-nicht-schreiben",
    "ruhezone",
)

_CHAOS_ALPHABET = string.ascii_lowercase + string.digits + "-"


def random_name(rng: random.Random, *, avoid: str | None = None) -> str:
    """Pick a name from :data:`NAMES`, never the one currently in use."""
    choices = [name for name in NAMES if name != avoid] or list(NAMES)
    return rng.choice(choices)


def chaos_name(rng: random.Random) -> str:
    """Random 7-26 character channel name, the hardest form for a blacklist to follow."""
    length = rng.randint(7, 26)
    name = "".join(rng.choice(_CHAOS_ALPHABET) for _ in range(length)).strip("-")
    return name or "x" * length
