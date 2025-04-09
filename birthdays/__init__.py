"""Package for Birthdays cog."""

import json
from pathlib import Path

from redbot.core.bot import Red

from .birthdays import Birthdays

with Path(__file__).parent.joinpath("info.json").open() as fp:
    __red_end_user_data_statement__ = json.load(fp)["end_user_data_statement"]


async def setup(bot: Red) -> None:
    """Load Birthdays cog."""
    cog = Birthdays(bot)
    await cog.initialize()
    await bot.add_cog(cog)
