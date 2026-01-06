"""InviteWhitelist cog for Red-DiscordBot"""

from .invitewhitelist import InviteWhitelist


async def setup(bot):
    """Load InviteWhitelist cog."""
    cog = InviteWhitelist(bot)
    await bot.add_cog(cog)
    await cog.initialize()
