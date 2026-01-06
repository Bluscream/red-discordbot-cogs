"""InWhitelist cog for Red-DiscordBot"""

from .inwhitelist import InWhitelist


async def setup(bot):
    """Load InWhitelist cog."""
    cog = InWhitelist(bot)
    await bot.add_cog(cog)
    await cog.initialize()
