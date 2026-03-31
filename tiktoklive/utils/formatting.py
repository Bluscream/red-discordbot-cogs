import discord
from redbot.core.utils.chat_formatting import bold
from .metadata import get_user_id, get_nickname, get_user_link

def format_event(event, event_type: str, color: discord.Color = discord.Color.blue(), can_embed: bool = True):
    """
    Formats a TikTok event into either a discord.Embed or a raw string with markdown links.
    """
    nick = get_nickname(event)
    u_id = get_user_id(event)
    user_link = get_user_link(event)
    
    # Event specific logic
    content = ""
    icon = ""
    
    if event_type == "comment":
        icon = "💬"
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

    if can_embed:
        embed = discord.Embed(
            title=f"{icon} {event_type.capitalize()}",
            description=f"{user_link} {content}",
            color=color
        )
        if hasattr(event, 'user_info'):
            avatar = getattr(event.user_info.avatar_thumb, 'url_list', [None])[0]
            if avatar:
                embed.set_thumbnail(url=avatar)
        return embed
    else:
        return f"{icon} **{user_link}** {content}"
