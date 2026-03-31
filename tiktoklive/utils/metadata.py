import logging

log = logging.getLogger("red.blu.tiktoklive.metadata")

def get_user_id(event):
    """Extreme Robust user ID extraction by bypassing buggy properties."""
    # 1. Prioritize raw user_info or other direct fields to avoid the buggy .user property
    for field in ['user_info', 'operator_info', 'current_user_info']:
        info = getattr(event, field, None)
        if info:
            for attr in ['unique_id', 'username', 'uniqueId', 'display_id', 'nickname']:
                val = getattr(info, attr, None)
                if val: return str(val)
    
    # 2. Try the property but wrap in try-except to catch library-level crashes
    try:
        if hasattr(event, 'user') and event.user:
            return str(getattr(event.user, 'unique_id', 'Unknown'))
    except:
        pass
        
    return "Unknown"

def get_nickname(event):
    """Extreme Robust nickname extraction by bypassing buggy properties."""
    for field in ['user_info', 'operator_info', 'current_user_info']:
        info = getattr(event, field, None)
        if info:
            for attr in ['nickname', 'nick_name', 'nickName', 'username', 'display_id', 'unique_id']:
                val = getattr(info, attr, None)
                if val: return str(val)

    try:
        if hasattr(event, 'user') and event.user:
            return str(getattr(event.user, 'nickname', 'Unknown'))
    except:
        pass

    return "Unknown"

def get_user_link(event):
    """Returns a clickable markdown link to the user's TikTok profile."""
    u_id = get_user_id(event)
    nick = get_nickname(event)
    if u_id == "Unknown":
        return nick
    return f"[{nick}](https://tiktok.com/@{u_id})"
