import asyncio
import discord
from datetime import datetime
from redbot.core.bot import Red
from .base import BaseTarget
from ..models import UEVRProfile
import logging

log = logging.getLogger("red.blu.uevr_webhooks")

class DiscordChannelTarget(BaseTarget):
    """Target for posting embeds directly to Discord channels using the bot's session."""
    
    def __init__(self, bot: Red):
        self.bot = bot
        self._rate_limited_until = {} # chan_id -> timestamp
        
    def to_embed(self, profile: UEVRProfile) -> discord.Embed:
        """Converts profile to a native discord.Embed object."""
        return discord.Embed.from_dict(self.to_discord_embed(profile))
        
    async def send(self, profile: UEVRProfile, session, channels: list[int]) -> None:
        if not channels:
            return
            
        discord_embed = self.to_embed(profile)
        now = datetime.utcnow().timestamp()
        
        for chan_id in channels:
            # Skip if we know this channel is rate limited
            if chan_id in self._rate_limited_until:
                if now < self._rate_limited_until[chan_id]:
                    # Periodically clean up old entries
                    continue
                else:
                    del self._rate_limited_until[chan_id]

            try:
                channel = self.bot.get_channel(chan_id)
                if channel:
                    msg = await channel.send(embed=discord_embed, allowed_mentions=discord.AllowedMentions.none())
                    log.info(f"[Targets] Sent profile embed to #{channel.name} ({chan_id})")
                    if hasattr(channel, "is_news") and channel.is_news():
                        try:
                            # Use a short timeout to avoid blocking for an hour on 429
                            await asyncio.wait_for(msg.publish(), timeout=10.0)
                            log.debug(f"[Targets] Published message in #{channel.name}")
                        except (asyncio.TimeoutError, discord.HTTPException) as e:
                            # If we hit a timeout or 429, mark this channel as limited for 1 hour
                            # (standard news channel cooldown)
                            self._rate_limited_until[chan_id] = now + 3600
                            reason = "Timeout/429" if isinstance(e, asyncio.TimeoutError) else str(e)
                            log.warning(f"[Targets] Publishing in #{channel.name} is rate limited ({reason}). Skipping further attempts for 1 hour.")
                        except discord.Forbidden:
                            log.warning(f"[Targets] Missing 'Manage Messages' to publish in #{channel.name}")
                else:
                    log.warning(f"[Targets] Could not find channel ID {chan_id}.")
            except discord.Forbidden:
                log.warning(f"[Targets] Missing permissions for channel {chan_id}.")
            except Exception as e:
                log.error(f"[Targets] Error posting to channel {chan_id}: {e}")
