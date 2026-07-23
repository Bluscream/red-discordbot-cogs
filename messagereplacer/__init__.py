"""MessageReplacer cog for Red-DiscordBot"""

from .messagereplacer import MessageReplacer

async def setup(bot):
    """Load MessageReplacer cog."""
    cog = MessageReplacer(bot)
    await bot.add_cog(cog)
