from .stream_sync import StreamSync

async def setup(bot):
    cog = StreamSync(bot)
    await bot.add_cog(cog)
