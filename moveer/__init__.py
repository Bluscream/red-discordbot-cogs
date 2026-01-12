"""Moveer cog for Red-DiscordBot"""

from .moveer import Moveer


async def setup(bot):
    """Load Moveer cog."""
    cog = Moveer(bot)
    await bot.add_cog(cog)
