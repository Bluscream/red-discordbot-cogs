"""UEVR Webhooks cog for Red-DiscordBot"""

from .uevr_webhooks import UEVRWebhooks

async def setup(bot):
    """Load UEVRWebhooks cog."""
    cog = UEVRWebhooks(bot)
    await bot.add_cog(cog)
