"""TikTokLive cog for Red-DiscordBot"""

from .tiktoklive import TikTokLive

async def setup(bot):
    """Load TikTokLive cog."""
    cog = TikTokLive(bot)
    await bot.add_cog(cog)
