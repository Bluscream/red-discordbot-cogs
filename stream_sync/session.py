from typing import Optional, Any
import discord

class StreamSession:
    """
    Unified data container for any monitored stream (TikTok, Twitch, YouTube).
    """
    def __init__(self, platform: str, channel_id: str, voice_channel: int, text_channel: Any, 
                 voice_enabled: bool = True, chat_enabled: bool = True, last_live: float = 0):
        self.platform = platform.lower()
        self.channel_id = channel_id
        self.voice_channel = voice_channel
        self.text_channel = text_channel
        
        self.voice_enabled = voice_enabled
        self.chat_enabled = chat_enabled
        self.last_live = last_live
        
        self.is_managed = False  # True if text_channel is a webhook we own
        self.is_live = False
        self.current_viewers = 0
        self.voice_client: Optional[discord.VoiceClient] = None
        self.hls_url: Optional[str] = None
        self.original_nick: Optional[str] = None
        self.avatar_url: Optional[str] = None
        
        # Background task for this specific session if needed (TikTok uses this)
        self.monitor_task: Optional[Any] = None
        self.last_status_check: float = 0
