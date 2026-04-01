from .youtubelive import YouTubeLive

async def setup(bot):
    cog = YouTubeLive(bot)
    await bot.add_cog(cog)
