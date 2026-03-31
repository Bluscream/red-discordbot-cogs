import asyncio
from typing import Optional, Union
from TikTokLive import TikTokLiveClient
import discord

class TikTokLiveSession:
    def __init__(self, username: str, voice_channel: int, text_channel: Union[int, str]):
        self.username = username
        self.voice_channel = voice_channel
        self.text_channel = text_channel
        
        self.client: Optional[TikTokLiveClient] = None
        self.voice_client: Optional[discord.VoiceClient] = None
        self.hls_url: Optional[str] = None
        self.is_monitoring = True
