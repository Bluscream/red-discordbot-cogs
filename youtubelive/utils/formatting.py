import discord
from typing import Optional

def format_status_embed(username: str, title: str, viewers: int = 0, thumbnail_url: Optional[str] = None):
    """Creates a standardized 'Live' embed."""
    embed = discord.Embed(
        title=f"🔴 {username} is LIVE on YouTube!",
        description=title,
        color=discord.Color.red(),
        url=f"https://www.youtube.com/channel/{username}/live"
    )
    if viewers > 0:
        embed.add_field(name="Viewers", value=f"{viewers:,}", inline=True)
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)
    return embed

def sanitize_mentions(text: str):
    """Simple sanitization to prevent accidental @everyone in bridged chat."""
    return text.replace("@everyone", "@\u200beveryone").replace("@here", "@\u200bhere")
