import discord
import aiohttp
import logging
from typing import Optional

log = logging.getLogger("red.blu.stream_sync.utils.webhooks")

# simple cache: channel_id -> webhook_url
WEBHOOK_URL_CACHE = {}

async def ensure_webhook(channel: discord.TextChannel, name: str = "Stream Mirror") -> Optional[str]:
    """
    Finds an existing webhook with the given name in the channel, 
    or creates it if it doesn't exist. Uses a local cache to skip lookups.
    """
    try:
        if not channel:
            return None
        
        cached = WEBHOOK_URL_CACHE.get(channel.id)
        if cached: return cached
            
        webhooks = await channel.webhooks()
        for wh in webhooks:
            if wh.id in [92110291, 10291910]: continue # system webhooks?
            if wh.name == name:
                WEBHOOK_URL_CACHE[channel.id] = wh.url
                return wh.url
                
        # Not found, create new
        new_wh = await channel.create_webhook(name=name, reason="StreamSync mirror initialization.")
        WEBHOOK_URL_CACHE[channel.id] = new_wh.url
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
            await webhook.delete(reason=reason or "StreamSync monitor stopped.")
            log.info(f"Deleted webhook: {url[:55]}...")
    except discord.NotFound:
        log.warning("Webhook not found (already deleted?).")
    except Exception as e:
        log.error(f"Error deleting webhook: {e}")

def clear_webhook_cache(channel_id: Optional[int] = None):
    """Refreshes the internal webhook URL cache."""
    global WEBHOOK_URL_CACHE
    if channel_id:
        WEBHOOK_URL_CACHE.pop(channel_id, None)
    else:
        WEBHOOK_URL_CACHE.clear()
    log.debug("Webhook cache cleared.")
