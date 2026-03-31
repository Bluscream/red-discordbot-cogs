import logging

log = logging.getLogger("red.blu.tiktoklive.metadata")

def get_user_id(event):
    """Extreme Robust user ID extraction by bypassing buggy properties."""
    # 1. Prioritize raw message or user_info fields to avoid the buggy .user property
    containers = ['user_info', 'operator_info', 'current_user_info', '_message']
    for field in containers:
        info = getattr(event, field, None)
        if not info: continue
        
        # If it's the raw message, it might have a .user field
        if field == '_message' and hasattr(info, 'user'):
            info = info.user

        for attr in ['unique_id', 'username', 'uniqueId', 'display_id', 'nickname']:
            val = getattr(info, attr, None)
            if val: return str(val)
    
    # 2. Hard-coded fallbacks for events that might have direct attributes
    for attr in ['unique_id', 'nickname']:
        val = getattr(event, attr, None)
        if val: return str(val)
        
    return "Unknown"

def get_nickname(event):
    """Extreme Robust nickname extraction by bypassing buggy properties."""
    containers = ['user_info', 'operator_info', 'current_user_info', '_message']
    for field in containers:
        info = getattr(event, field, None)
        if not info: continue
        
        if field == '_message' and hasattr(info, 'user'):
            info = info.user

        for attr in ['nickname', 'nick_name', 'nickName', 'username', 'display_id', 'unique_id']:
            val = getattr(info, attr, None)
            if val: return str(val)

    # 2. Hard-coded fallbacks
    for attr in ['nickname', 'username']:
        val = getattr(event, attr, None)
        if val: return str(val)

    return "Unknown"

def get_user_link(event):
    """Returns a clickable markdown link to the user's TikTok profile."""
    u_id = get_user_id(event)
    nick = get_nickname(event)
    if u_id == "Unknown":
        return nick
    return f"[{nick}](https://tiktok.com/@{u_id})"
