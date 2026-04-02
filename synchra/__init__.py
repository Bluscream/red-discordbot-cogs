from .synchra import Synchra

async def setup(bot):
    await bot.add_cog(Synchra(bot))
