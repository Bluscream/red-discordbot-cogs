import logging
from typing import Optional, List, Dict, Any, Union
from uuid import UUID
import httpx

# The Synchra SDK (v2.0)
from synchra import SynchraClient
from synchra.models.resources import Channel, ChannelProvider

log = logging.getLogger("red.blu.synchra.api")

class SynchraAPIManager:
    """Wrapper for the Synchra SDK to handle authentication and high-level operations."""
    
    def __init__(self, config):
        self.config = config
        self.client: Optional[SynchraClient] = None
        self._initialized = False

    async def initialize(self):
        """Initialize the SynchraClient with credentials from config."""
        access_token = await self.config.access_token()
        client_id = await self.config.client_id()
        client_secret = await self.config.client_secret()
        
        if not access_token and not (client_id and client_secret):
            log.warning("Synchra API credentials missing. API manager not initialized.")
            return False

        self.client = SynchraClient(
            access_token=access_token,
            client_id=client_id,
            client_secret=client_secret
        )
        self._initialized = True
        log.info("Synchra API Manager initialized.")
        return True

    async def close(self):
        """Close the API client."""
        if self.client:
            await self.client.close()
            self.client = None
            self._initialized = False

    @property
    def is_ready(self) -> bool:
        return self._initialized and self.client is not None

    async def get_channel_by_uuid(self, uuid: Union[str, UUID]) -> Optional[Channel]:
        """Fetch a channel by its Synchra UUID."""
        if not self.is_ready: return None
        try:
            return await self.client.channels.get(UUID(str(uuid)))
        except Exception as e:
            log.error(f"Error fetching channel {uuid}: {e}")
            return None

    async def lookup_channel(self, platform: str, handle: str) -> Optional[Channel]:
        """Look up a channel UUID using platform and handle."""
        if not self.is_ready: return None
        try:
            # Synchra list() supports filtering by provider and provider_channel_name
            channels = await self.client.channels.list(
                provider=platform.lower(),
                provider_channel_name=handle
            )
            if channels:
                return channels[0]
        except Exception as e:
            log.error(f"Error looking up channel {platform}/{handle}: {e}")
        return None

    async def get_providers(self, channel_uuid: UUID) -> List[ChannelProvider]:
        """Get all providers for a channel."""
        if not self.is_ready: return []
        try:
            return await self.client.channels.list_providers(channel_uuid)
        except Exception as e:
            log.error(f"Error fetching providers for {channel_uuid}: {e}")
            return []
            
    async def get_hls_fallback(self, platform: str, handle: str) -> Optional[str]:
        """
        Fallback HLS resolution using yt-dlp.
        This is called if Synchra doesn't provide a direct stream URL.
        """
        import asyncio
        url_map = {
            "twitch": f"https://www.twitch.tv/{handle}",
            "youtube": f"https://www.youtube.com/@{handle}/live",
            "kick": f"https://kick.com/{handle}",
            "tiktok": f"https://www.tiktok.com/@{handle}/live"
        }
        
        target_url = url_map.get(platform.lower())
        if not target_url:
            return None

        # Call yt-dlp asynchronously
        cmd = ["yt-dlp", "-g", "--format", "best", target_url]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                hls_url = stdout.decode().strip()
                return hls_url
            else:
                log.warning(f"yt-dlp failed to resolve {target_url}: {stderr.decode()}")
        except Exception as e:
            log.error(f"yt-dlp execution error: {e}")
        
        return None
