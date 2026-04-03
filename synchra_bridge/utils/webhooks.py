import discord
import aiohttp
import logging
from typing import Optional

log = logging.getLogger("red.blu.synchra_bridge.utils.webhooks")

async def ensure_webhook(channel: discord.TextChannel, name: str = "Synchra Mirror") -> Optional[str]:
    """
    Finds an existing webhook with the given name in the channel, 
    or creates it if it doesn't exist.
    Returns the webhook URL.
    """
    try:
        if not channel:
            return None
        
        if not channel.permissions_for(channel.guild.me).manage_webhooks:
            log.debug(f"Missing Manage Webhooks permission in {channel.name}")
            return None
            
        webhooks = await channel.webhooks()
        for wh in webhooks:
            if wh.name == name:
                return wh.url
                
        # Not found, create new
        new_wh = await channel.create_webhook(name=name, reason="Synchra chat mirror initialization.")
        return new_wh.url
        
    except discord.Forbidden:
        log.error(f"Missing 'Manage Webhooks' permission in {channel.name}")
    except Exception as e:
        log.error(f"Failed to ensure webhook in {channel.name}: {e}")
    return None

async def send_webhook_message(url: str, content: str, username: str, avatar_url: Optional[str] = None):
    """Sends a message via webhook with custom username and avatar."""
    try:
        async with aiohttp.ClientSession() as session:
            webhook = discord.Webhook.from_url(url, session=session)
            await webhook.send(
                content=content,
                username=username,
                avatar_url=avatar_url,
                allowed_mentions=discord.AllowedMentions.none() # Sanitize for safety
            )
    except Exception as e:
        log.error(f"Failed to send webhook message: {e}")
        return False
    return True
