from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
import logging
import discord
import yt_dlp
from redbot.core.bot import Red

class StreamPlatform(ABC):
    """
    Abstract Base Class for all StreamSync platform providers (TikTok, Twitch, YouTube).
    """
    def __init__(self, bot: Red, action_queue: Any, config: Any, cog: Any):
        self.bot = bot
        self.action_queue = action_queue
        self.config = config
        self.cog = cog
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
        
    async def _get_hls_via_ytdlp(self, url: str) -> Optional[str]:
        """Shared helper to extract the best .m3u8 URL using yt-dlp."""
        ydl_opts = {
            'format': 'bestaudio/best',
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }
        try:
            # Use run_in_executor since yt-dlp's extract_info is blocking
            def _extract():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    return ydl.extract_info(url, download=False)
            
            info = await self.bot.loop.run_in_executor(None, _extract)
            if not info: 
                self.log.warning(f"yt-dlp: No info returned for {url}")
                return None
            
            # Check for direct manifest URL (m3u8)
            hls = info.get('url') or info.get('manifest_url')
            if hls:
                self.log.info(f"yt-dlp: Found HLS URL for {self.name}: {hls[:50]}...")
            else:
                self.log.warning(f"yt-dlp: No HLS URL found in info for {url}")
            return hls
        except Exception as e:
            self.log.error(f"yt-dlp: Extraction failed for {url}: {e}")
        return None

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
