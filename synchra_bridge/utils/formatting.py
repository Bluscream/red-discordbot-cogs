import re
from typing import Optional

def sanitize_mentions(text: str) -> str:
    """Escapes @everyone, @here, and role mentions to prevent accidental pings."""
    if not text:
        return text
    
    # Escape @everyone and @here
    text = text.replace("@everyone", "@\u200beveryone").replace("@here", "@\u200bhere")
    
    # Escape role mentions (e.g. <@&123456789>)
    text = re.sub(r"<@&(\d+)>", r"<@& \1>", text)
    
    # Escape user mentions (optional, but safer for remote input)
    text = re.sub(r"<@!?(\d+)>", r"<@\1>", text)
    
    return text

def clean_name(name: str) -> str:
    """Strips newlines and excessive whitespace from usernames/handles."""
    if not name:
        return "Unknown"
    
    # Remove newlines and tabs
    name = re.sub(r"[\r\n\t]+", " ", name)
    
    # Strip leading/trailing whitespace
    name = name.strip()
    
    # Cap length for Discord constraints (username limit is 32-80 depending on context)
    return name[:80]
