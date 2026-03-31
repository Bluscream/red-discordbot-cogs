from .tiktoklive import TikTokLive

async def setup(bot):
    await bot.add_cog(TikTokLive(bot))
