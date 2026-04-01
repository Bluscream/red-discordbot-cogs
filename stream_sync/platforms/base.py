from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
import logging
import discord
from redbot.core.bot import Red

class StreamPlatform(ABC):
    """
    Abstract Base Class for all StreamSync platform providers (TikTok, Twitch, YouTube).
    """
    def __init__(self, bot: Red, action_queue: Any, config: Any):
        self.bot = bot
        self.action_queue = action_queue
        self.config = config
        self.name = self.__class__.__name__.replace("Platform", "").lower()
        self.log = logging.getLogger(f"red.blu.stream_sync.platforms.{self.name}")

    @abstractmethod
    async def is_live(self, channel_id: str) -> Dict[str, Any]:
        """
        Check if a channel is live. 
        Returns a dict with 'live' (bool), 'title' (str), 'viewers' (int), and 'thumbnail' (str).
        """
        pass

    @abstractmethod
    async def get_hls_url(self, channel_id: str) -> Optional[str]:
        """Retrieve the current HLS (.m3u8) stream URL for audio playback."""
        pass

    async def get_metadata(self, channel_id: str) -> Dict[str, Any]:
        """Optional: Fetch additional metadata like avatar_url or category."""
        return {}

    async def on_live_start(self, session: Any):
        """Optional callback when a stream starts."""
        pass

    async def on_live_end(self, session: Any):
        """Optional callback when a stream ends."""
        pass

    async def start_chat(self, session: Any):
        """Start the live chat synchronization for this session."""
        pass

    async def stop_chat(self, session: str):
        """Stop the live chat synchronization for this channel ID."""
        pass
