import discord
from redbot.core.utils.chat_formatting import bold
from .metadata import get_user_id, get_nickname, get_user_link, get_user_handle, get_user_avatar

def format_event(event, event_type: str, color: discord.Color = discord.Color.blue(), 
                 can_embed: bool = True, streamer_name: str = "Unknown", is_webhook: bool = False):
    """
    Formats a TikTok event into either a discord.Embed or a raw string with markdown links.
    """
    nick = get_nickname(event)
    handle = get_user_handle(event)
    user_link = get_user_link(event)
    avatar = get_user_avatar(event)
    tiktok_url = f"https://tiktok.com/@{handle}" if handle != "unknown" else None
    
    content = ""
    icon = ""
    
    if event_type == "comment":
        icon = "💬"
        # Accessing raw comment field from protobuf
        content = getattr(event, 'comment', 'No comment provided.')
    elif event_type == "gift":
        icon = "🎁"
        gift_name = getattr(event.gift, 'name', 'Unknown Gift')
        count = getattr(event, 'repeat_count', 1)
        content = f"sent {bold(f'{count}x {gift_name}')}!"
    elif event_type == "follow":
        icon = "👤"
        content = "followed the streamer!"
    elif event_type == "share":
        icon = "🔗"
        content = "shared the live!"
    elif event_type == "join":
        icon = "👋"
        content = "joined the room!"

    # Special handling for webhooks: comments should be raw text to look like chat
    if is_webhook and event_type == "comment":
        return content

    if can_embed:
        embed = discord.Embed(
            description=content,
            color=color,
            timestamp=discord.utils.utcnow()
        )
        embed.set_author(name=nick, url=tiktok_url, icon_url=avatar)
        embed.set_footer(text=f"Monitoring @{streamer_name}")
        
        return embed
    else:
        return f"{icon} **{user_link}** {content}"
