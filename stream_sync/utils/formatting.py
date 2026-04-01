import discord
from typing import Optional

def format_status_embed(platform: str, username: str, title: str, 
                        extra: Optional[str] = None, viewers: int = 0, 
                        thumbnail_url: Optional[str] = None):
    """Unified status embed formatter for all StreamSync platforms."""
    
    colors = {
        "tiktok": discord.Color.from_rgb(0, 0, 0),
        "twitch": discord.Color.purple(),
        "youtube": discord.Color.red()
    }
    
    color = colors.get(platform.lower(), discord.Color.blue())
    display_platform = platform.capitalize()
    
    embed = discord.Embed(
        title=f"🔴 {username} is LIVE on {display_platform}!",
        description=title,
        color=color
    )
    
    if platform.lower() == "tiktok":
        embed.url = f"https://www.tiktok.com/@{username}/live"
    elif platform.lower() == "twitch":
        embed.url = f"https://www.twitch.tv/{username}"
    elif platform.lower() == "youtube":
        embed.url = f"https://www.youtube.com/@{username}/live" if username.startswith("@") else f"https://www.youtube.com/channel/{username}/live"

    if extra:
        embed.add_field(name="Category" if platform.lower() == "twitch" else "Status", value=extra, inline=True)
    
    if viewers > 0:
        embed.add_field(name="Viewers", value=f"{viewers:,}", inline=True)
        
    if thumbnail_url:
        thumb = thumbnail_url
        if platform.lower() == "twitch":
            thumb = thumb.replace("{width}", "1280").replace("{height}", "720")
        embed.set_image(url=thumb)
        
    return embed

def sanitize_mentions(text: str):
    """Simple sanitization to prevent accidental @everyone in bridged chat."""
    return text.replace("@everyone", "@\u200beveryone").replace("@here", "@\u200bhere")
