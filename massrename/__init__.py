"""MassRename cog for Red-DiscordBot"""

from .massrename import MassRename

async def setup(bot):
    """Load MassRename cog."""
    cog = MassRename(bot)
    await bot.add_cog(cog)
