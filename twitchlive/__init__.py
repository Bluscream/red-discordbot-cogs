from .twitchlive import TwitchLive

async def setup(bot):
    cog = TwitchLive(bot)
    await bot.add_cog(cog)
