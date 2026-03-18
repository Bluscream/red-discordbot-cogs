import discord
from redbot.core.bot import Red
from .base import BaseTarget
from ..models import UEVRProfile
import logging

log = logging.getLogger("red.blu.uevr_webhooks")

class DiscordChannelTarget(BaseTarget):
    """Target for posting embeds directly to Discord channels using the bot's session."""
    
    def __init__(self, bot: Red):
        self.bot = bot
        
    def to_embed(self, profile: UEVRProfile) -> discord.Embed:
        """Converts profile to a native discord.Embed object."""
        return discord.Embed.from_dict(self.to_discord_embed(profile))
        
    async def send(self, profile: UEVRProfile, session, channels: list[int]) -> None:
        if not channels:
            return
            
        discord_embed = self.to_embed(profile)
        
        for chan_id in channels:
            try:
                channel = self.bot.get_channel(chan_id)
                if channel:
                    await channel.send(embed=discord_embed)
                else:
                    log.warning(f"[Targets] Could not find channel ID {chan_id}.")
            except discord.Forbidden:
                log.warning(f"[Targets] Missing permissions for channel {chan_id}.")
            except Exception as e:
                log.error(f"[Targets] Error posting to channel {chan_id}: {e}")
