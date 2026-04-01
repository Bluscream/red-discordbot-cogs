import asyncio
from typing import Optional, Union
from TikTokLive import TikTokLiveClient
import discord

class TikTokLiveSession:
    def __init__(self, username: str, voice_channel: int, text_channel: Union[int, str], discord_channel_id: Optional[int] = None):
        self.username = username
        self.voice_channel = voice_channel
        self.text_channel = text_channel # Can be ID or URL
        self.discord_channel_id = discord_channel_id
        
        self.client: Optional[TikTokLiveClient] = None
        self.voice_client: Optional[discord.VoiceClient] = None
        self.hls_url: Optional[str] = None
        self.is_monitoring = True
        
        # Managed Webhook Tracking
        self.webhook_id: Optional[int] = None
        self.is_managed = False
        
        # Original Identity & VC State (for revert)
        self.original_nick: Optional[str] = None
        self.original_avatar_url: Optional[str] = None # Or bytes
        self.original_vc_status: Optional[str] = None
