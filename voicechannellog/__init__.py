"""Package for the VoiceChannelLog cog."""

import json
from pathlib import Path

from redbot.core.bot import Red

from .voicechannellog import VoiceChannelLog

with Path(__file__).parent.joinpath("info.json").open(encoding="utf-8") as fp:
    __red_end_user_data_statement__ = json.load(fp)["end_user_data_statement"]


async def setup(bot: Red) -> None:
    """Load the VoiceChannelLog cog."""
    await bot.add_cog(VoiceChannelLog(bot))
