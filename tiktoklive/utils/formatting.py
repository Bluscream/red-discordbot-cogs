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
        # Robust gift info extraction from mGift (found in logs)
        mgift = getattr(event, 'm_gift', getattr(event, 'mGift', event.gift))
        gift_name = getattr(mgift, 'name', 'Unknown Gift')
        count = getattr(event, 'repeat_count', 1)
        diamonds = getattr(mgift, 'diamondCount', getattr(mgift, 'diamond_count', 0))
        
        # Gift icon extraction
        gift_icon = None
        icon_obj = getattr(mgift, 'icon', None)
        if icon_obj:
            urls = getattr(icon_obj, 'm_urls', getattr(icon_obj, 'mUrls', []))
            if urls: gift_icon = str(urls[0])
            
        content = f"sent {bold(f'{count}x {gift_name}')}!"
        if diamonds > 0:
            content += f" ({diamonds * count} 💎)"

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
        
        if event_type == "gift" and gift_icon:
            embed.set_thumbnail(url=gift_icon)
            
        embed.set_footer(text=f"Monitoring @{streamer_name}")
        
        return embed
    else:
        return f"{icon} **{user_link}** {content}"
