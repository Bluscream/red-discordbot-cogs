"""Bluscream cog for Red-DiscordBot"""

from .bluscream import Bluscream


async def setup(bot):
    """Load Bluscream cog."""
    cog = Bluscream(bot)
    await bot.add_cog(cog)
