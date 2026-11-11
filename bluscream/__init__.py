"""Bluscream cog for Red-DiscordBot."""

from redbot.core.bot import Red

from .bluscream import Bluscream


async def setup(bot: Red) -> None:
    """Load the Bluscream cog."""
    await bot.add_cog(Bluscream(bot))
