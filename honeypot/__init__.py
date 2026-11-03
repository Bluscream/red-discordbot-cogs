"""Package for the Honeypot cog."""

import json
from pathlib import Path

from redbot.core.bot import Red

from .commands import Honeypot

with Path(__file__).parent.joinpath("info.json").open(encoding="utf-8") as fp:
    __red_end_user_data_statement__ = json.load(fp)["end_user_data_statement"]


async def setup(bot: Red) -> None:
    """Load the Honeypot cog."""
    await bot.add_cog(Honeypot(bot))
