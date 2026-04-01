from typing import Optional, Any
import discord

class YouTubeLiveSession:
    """
    Data container for an active YouTube monitoring session.
    """
    def __init__(self, channel_id: str, voice_channel: int, text_channel: Any, discord_channel_id: Optional[int] = None):
        self.channel_id = channel_id
        self.username = channel_id # For YT, they are often the same if using handle/ID
        self.voice_channel = voice_channel
        self.text_channel = text_channel
        self.discord_channel_id = discord_channel_id
        
        self.is_managed = False  # If True, text_channel is a webhook URL we created
        self.is_live = False
        self.voice_client: Optional[discord.VoiceClient] = None
        self.hls_url: Optional[str] = None
        self.original_nick: Optional[str] = None
        
        # State for the background loop
        self.monitor_task: Optional[Any] = None
