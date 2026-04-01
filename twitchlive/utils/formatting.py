import discord
from typing import Optional

def format_status_embed(username: str, title: str, game: str = "", viewers: int = 0, thumbnail_url: Optional[str] = None):
    """Creates a standardized 'Live' embed."""
    embed = discord.Embed(
        title=f"🔴 {username} is LIVE on Twitch!",
        description=title,
        color=discord.Color.purple(), # Twitch purple
        url=f"https://www.twitch.tv/{username}"
    )
    if game:
        embed.add_field(name="Category", value=game, inline=True)
    if viewers > 0:
        embed.add_field(name="Viewers", value=f"{viewers:,}", inline=True)
    if thumbnail_url:
        # Twitch thumbnail URLs often have {width} and {height}
        thumb = thumbnail_url.replace("{width}", "1280").replace("{height}", "720")
        embed.set_image(url=thumb)
    return embed

def sanitize_mentions(text: str):
    """Simple sanitization to prevent accidental @everyone in bridged chat."""
    return text.replace("@everyone", "@\u200beveryone").replace("@here", "@\u200bhere")
