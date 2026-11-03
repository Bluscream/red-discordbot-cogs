"""Optional behaviours, mirroring the experiments of the RiskyMH Honeypot bot."""

from collections.abc import Mapping
from enum import StrEnum


class Experiment(StrEnum):
    """Every optional behaviour the cog supports."""

    FORWARD_MESSAGE = "forward-message"
    REINVITE = "reinvite"
    NO_WARNING = "no-warning-msg"
    NO_DM = "no-dm"
    CHANNEL_WARMER = "channel-warmer"
    RANDOM_NAME = "random-channel-name"
    RANDOM_NAME_CHAOS = "random-channel-name-chaos"
    RECREATE_CHANNEL = "recreate-channel"
    TIMEOUT_FIRST = "timeout-first"
    ONLY_RECENT_DELETE = "only-recent-delete"
    ENSURE_DELETE = "ensure-msg-delete"


DESCRIPTIONS: Mapping[Experiment, str] = {
    Experiment.FORWARD_MESSAGE: "Forward the triggering message into the log channel for review.",
    Experiment.REINVITE: "Put a permanent rejoin invite in the DM (recommended with softban).",
    Experiment.NO_WARNING: "Do not post the warning message, so the channel looks empty.",
    Experiment.NO_DM: "Do not DM members who trigger the honeypot.",
    Experiment.CHANNEL_WARMER: "Once a day send and delete a message so the channel looks active.",
    Experiment.RANDOM_NAME: "Rename the honeypot channel daily from a built-in name list.",
    Experiment.RANDOM_NAME_CHAOS: "Rename the honeypot channel daily to random characters.",
    Experiment.RECREATE_CHANNEL: "Recreate the channel daily so it gets a new ID (old messages are lost).",
    Experiment.TIMEOUT_FIRST: "Time the member out for 1 hour before acting, so a fast rejoin stays muted.",
    Experiment.ONLY_RECENT_DELETE: "Delete only the last 15 minutes of their messages instead of 1 hour.",
    Experiment.ENSURE_DELETE: "Delete the trigger at once and sweep for leftover messages 2 minutes later.",
}

DAILY: frozenset[Experiment] = frozenset(
    {
        Experiment.CHANNEL_WARMER,
        Experiment.RANDOM_NAME,
        Experiment.RANDOM_NAME_CHAOS,
        Experiment.RECREATE_CHANNEL,
    }
)

# Bot permissions each experiment needs on top of the base set (Ban Members etc.).
REQUIRED_PERMISSIONS: Mapping[Experiment, tuple[str, ...]] = {
    Experiment.FORWARD_MESSAGE: ("read_message_history",),
    Experiment.REINVITE: ("create_instant_invite",),
    Experiment.RANDOM_NAME: ("manage_channels",),
    Experiment.RANDOM_NAME_CHAOS: ("manage_channels",),
    Experiment.RECREATE_CHANNEL: ("manage_channels",),
    Experiment.TIMEOUT_FIRST: ("moderate_members",),
    Experiment.ENSURE_DELETE: ("manage_messages", "read_message_history"),
}


def parse(value: str) -> Experiment | None:
    """Accept ``forward-message``, ``forward_message`` or ``FORWARD MESSAGE``."""
    normalised = value.strip().lower().replace("_", "-").replace(" ", "-")
    try:
        return Experiment(normalised)
    except ValueError:
        return None
