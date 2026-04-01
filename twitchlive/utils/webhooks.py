import discord
import aiohttp
import logging
from typing import Optional

log = logging.getLogger("red.blu.twitchlive.utils.webhooks")

async def ensure_webhook(channel: discord.TextChannel, name: str = "Twitch Mirror") -> Optional[str]:
    """
    Finds an existing webhook with the given name in the channel, 
    or creates it if it doesn't exist.
    Returns the webhook URL.
    """
    try:
        if not channel:
            return None
            
        webhooks = await channel.webhooks()
        for wh in webhooks:
            if wh.name == name:
                return wh.url
                
        # Not found, create new
        new_wh = await channel.create_webhook(name=name, reason="Twitch Live mirror initialization.")
        return new_wh.url
        
    except discord.Forbidden:
        log.error(f"Missing 'Manage Webhooks' permission in {channel.name}")
    except Exception as e:
        log.error(f"Failed to ensure webhook: {e}")
    return None

async def delete_webhook_by_url(url: str, reason: Optional[str] = None):
    """Safely deletes a webhook by its URL."""
    try:
        async with aiohttp.ClientSession() as session:
            webhook = discord.Webhook.from_url(url, session=session)
            await webhook.delete(reason=reason or "Twitch monitor stopped.")
            log.info(f"Deleted webhook: {url[:55]}...")
    except discord.NotFound:
        log.warning("Webhook not found (already deleted?).")
    except Exception as e:
        log.error(f"Error deleting webhook: {e}")
