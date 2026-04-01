import discord
from redbot.core.utils.chat_formatting import bold
from .metadata import get_user_id, get_nickname, get_user_link, get_user_handle, get_user_avatar

def sanitize_mentions(text: str) -> str:
    """Escapes @everyone and @here to prevent accidental pings."""
    if not text:
        return text
    return text.replace("@everyone", "\\@everyone").replace("@here", "\\@here")

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
        raw_comment = getattr(event, 'comment', 'No comment provided.')
        content = sanitize_mentions(raw_comment)
    elif event_type == "gift":
        icon = "🎁"
        # Robust gift info extraction from mGift (found in logs)
        mgift = getattr(event, 'm_gift', getattr(event, 'mGift', event.gift))
        gift_name = sanitize_mentions(getattr(mgift, 'name', 'Unknown Gift'))
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

    # Special handling for webhooks: No embeds, use italicized "action" style for non-comments
    if is_webhook:
        if event_type == "comment":
            return content
        elif event_type == "join":
            return f"*joined @{streamer_name}*"
        elif event_type == "gift":
            suffix = f" ({diamonds * count} 💎)" if diamonds > 0 else ""
            return f"*sent **{count}x {gift_name}**{suffix}*"
        elif event_type == "follow":
            return f"*followed the streamer!*"
        elif event_type == "share":
            return f"*shared the live!*"

    if can_embed:
        embed = discord.Embed(
            description=content,
            color=color,
            timestamp=discord.utils.utcnow()
        )
        embed.set_author(name=nick, url=tiktok_url, icon_url=avatar)
        
        if event_type == "gift" and gift_icon:
            embed.set_thumbnail(url=gift_icon)
            
        embed.set_footer(text=f"@{streamer_name}")
        
        return embed
    else:
        return f"{icon} **{user_link}** {content}"

def format_status_embed(streamer_name: str, event_type: str, viewer_count: int = 0):
    """Formats a LIVE/OFFLINE status embed."""
    tiktok_url = f"https://www.tiktok.com/@{streamer_name}/live"
    
    if event_type == "live":
        embed = discord.Embed(
            title=f"🔴 @{streamer_name} is LIVE!",
            description=f"Come join the stream! There are currently **{viewer_count}** viewers.",
            color=discord.Color.red(),
            url=tiktok_url
        )
        embed.add_field(name="Viewers", value=f"👥 {viewer_count}", inline=True)
    else:
        embed = discord.Embed(
            title=f"⚫ @{streamer_name} is now OFFLINE",
            description="The stream has ended. Stay tuned for the next one!",
            color=discord.Color.light_grey(),
            url=tiktok_url
        )
        
    embed.set_footer(text="TikTok Live Mirror")
    embed.set_thumbnail(url="https://www.edigitalagency.com.au/wp-content/uploads/TikTok-logo-PNG.png") # Generic TikTok logo fallback
    return embed
