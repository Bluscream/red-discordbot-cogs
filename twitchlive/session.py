from typing import Optional, Any
import discord

class TwitchLiveSession:
    """
    Data container for an active Twitch monitoring session.
    """
    def __init__(self, username: str, voice_channel: int, text_channel: Any, discord_channel_id: Optional[int] = None):
        self.username = username
        self.voice_channel = voice_channel
        self.text_channel = text_channel
        self.discord_channel_id = discord_channel_id
        
        self.is_managed = False
        self.is_live = False
        self.voice_client: Optional[discord.VoiceClient] = None
        self.hls_url: Optional[str] = None
        self.original_nick: Optional[str] = None
        self.avatar_url: Optional[str] = None
        
        # State for the background loop
        self.monitor_task: Optional[Any] = None
