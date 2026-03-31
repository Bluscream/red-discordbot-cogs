import logging

log = logging.getLogger("red.blu.tiktoklive.metadata")

def get_user_id(event):
    """Numerical ID extraction."""
    for field in ['user_info', 'current_user_info', 'fromUser', '_message']:
        info = getattr(event, field, None)
        if hasattr(info, 'user'): info = info.user
        if not info: continue
        
        for attr in ['id', 'user_id', 'uid']:
            val = getattr(info, attr, None)
            if val: return str(val)
    return "Unknown"

def get_user_handle(event):
    """Handle extraction (e.g. kitsu_dj) for URLs."""
    for field in ['user_info', 'current_user_info', 'fromUser', '_message']:
        info = getattr(event, field, None)
        if hasattr(info, 'user'): info = info.user
        if not info: continue
        
        for attr in ['username', 'unique_id', 'display_id']:
            val = getattr(info, attr, None)
            if val: return str(val).lower()
    return "unknown"

def get_nickname(event):
    """Nickname extraction (Display Name) for visual identity."""
    for field in ['user_info', 'current_user_info', 'fromUser', '_message']:
        info = getattr(event, field, None)
        if hasattr(info, 'user'): info = info.user
        if not info: continue
        
        for attr in ['nick_name', 'nickName', 'nickname', 'username']:
            val = getattr(info, attr, None)
            if val: return str(val)
    return "Unknown"

def get_user_avatar(event) -> str:
    """Extract High-Res Avatar URL."""
    for field in ['user_info', 'current_user_info', 'fromUser', '_message']:
        info = getattr(event, field, None)
        if hasattr(info, 'user'): info = info.user
        if not info: continue
        
        # Check avatarThumb structure found in logs
        thumb = getattr(info, 'avatar_thumb', getattr(info, 'avatarThumb', None))
        if thumb:
            urls = getattr(thumb, 'm_urls', getattr(thumb, 'mUrls', []))
            if urls: return str(urls[0])
            
    return ""

def get_user_link(event):
    """Returns a clickable markdown link: [Nickname](https://tiktok.com/@handle)."""
    handle = get_user_handle(event)
    nick = get_nickname(event)
    if handle == "unknown":
        return nick
    return f"[{nick}](https://tiktok.com/@{handle})"
