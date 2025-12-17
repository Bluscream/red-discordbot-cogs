"""Package for COD Status cog."""

import json
from pathlib import Path

from redbot.core.bot import Red

from .activisionstatus import ActivisionStatusCog

with Path(__file__).parent.joinpath("info.json").open() as fp:
    __red_end_user_data_statement__ = json.load(fp)["end_user_data_statement"]


async def setup(bot: Red) -> None:
    """Load cod-status cog."""
    cog = ActivisionStatusCog(bot)
    await cog.initialize()
    await bot.add_cog(cog)
