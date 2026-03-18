import asyncio
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
                    msg = await channel.send(embed=discord_embed)
                    if hasattr(channel, "is_news") and channel.is_news():
                        try:
                            # Use a short timeout to avoid blocking for an hour on 429
                            await asyncio.wait_for(msg.publish(), timeout=15.0)
                            log.debug(f"[Targets] Published message in #{channel.name}")
                        except asyncio.TimeoutError:
                            log.warning(f"[Targets] Publishing in #{channel.name} timed out (likely 429 rate limit). Skipping...")
                        except discord.Forbidden:
                            log.warning(f"[Targets] Missing 'Manage Messages' to publish in #{channel.name}")
                        except discord.HTTPException as e:
                            log.warning(f"[Targets] Failed to publish in #{channel.name}: {e}")
                else:
                    log.warning(f"[Targets] Could not find channel ID {chan_id}.")
            except discord.Forbidden:
                log.warning(f"[Targets] Missing permissions for channel {chan_id}.")
            except Exception as e:
                log.error(f"[Targets] Error posting to channel {chan_id}: {e}")
