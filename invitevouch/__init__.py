"""Package for the InviteVouch cog."""

import json
from pathlib import Path

from redbot.core.bot import Red

from .invitevouch import InviteVouch

with Path(__file__).parent.joinpath("info.json").open(encoding="utf-8") as fp:
    __red_end_user_data_statement__ = json.load(fp)["end_user_data_statement"]


async def setup(bot: Red) -> None:
    """Load the InviteVouch cog."""
    cog = InviteVouch(bot)
    await bot.add_cog(cog)
