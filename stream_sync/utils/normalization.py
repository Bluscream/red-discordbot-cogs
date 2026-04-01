import re
from typing import Optional

def normalize_channel_id(platform: str, input_str: str) -> str:
    """
    Standardize channel IDs/usernames from various input formats (URLs, @names, IDs).
    """
    input_str = input_str.strip()
    platform = platform.lower()

    if platform == "tiktok":
        # Matches: https://www.tiktok.com/@username/live, tiktok.com/@username, @username, username
        match = re.search(r'(?:tiktok\.com/)?@?([\w\.-]+)', input_str)
        if match:
            return match.group(1)
        return input_str.replace("@", "")

    elif platform == "twitch":
        # Matches: https://www.twitch.tv/username, twitch.tv/username, username
        match = re.search(r'(?:twitch\.tv/)?([\w]+)', input_str)
        if match:
            return match.group(1)
        return input_str

    elif platform == "youtube":
        # Matches: 
        # https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxx/live -> UCxxxxxxxxxxxxxxxxx
        # https://www.youtube.com/@username/live -> @username
        # @username -> @username
        # UCxxxxxxxxxxxxxxxxx -> UCxxxxxxxxxxxxxxxxx
        
        # Handle handles (@username)
        if "@" in input_str:
            match = re.search(r'(?:youtube\.cal?m?/)?(@[\w\.-]+)', input_str)
            if match: return match.group(1)
            return input_str if input_str.startswith("@") else f"@{input_str}"
            
        # Handle channel IDs
        channel_match = re.search(r'(?:channel/)?(UC[\w-]{22})', input_str)
        if channel_match:
            return channel_match.group(1)
            
        return input_str

    return input_str
