import asyncio
from typing import Optional
from TikTokLive import TikTokLiveClient
import discord

class TikTokLiveSession:
    def __init__(self, username: str, voice_channel_id: int, text_channel_id: int):
        self.username = username
        self.voice_channel_id = voice_channel_id
        self.text_channel_id = text_channel_id
        
        self.client: Optional[TikTokLiveClient] = None
        self.voice_client: Optional[discord.VoiceClient] = None
        self.hls_url: Optional[str] = None
        self.is_monitoring = True
