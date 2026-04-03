import logging
from typing import Optional, List, Dict, Any, Union
from uuid import UUID
import httpx

# The Synchra SDK (v2.0)
from synchra import SynchraClient
from synchra.models.resources import Channel, ChannelProvider

log = logging.getLogger("red.blu.synchra_bridge.api")

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

        try:
            self.client = SynchraClient(
                access_token=access_token,
                client_id=client_id,
                client_secret=client_secret
            )
            self._initialized = True
            log.info("Synchra API Manager initialized.")
            return True
        except Exception as e:
            log.error(f"Failed to initialize Synchra SDK: {e}")
            return False

    async def close(self):
        """Close the API client."""
        if self.client:
            try:
                await self.client.close()
            except: pass
            self.client = None
            self._initialized = False

    @property
    def is_ready(self) -> bool:
        """Whether the manager is correctly initialized with credentials."""
        return self._initialized and self.client is not None

    @property
    def is_connected(self) -> bool:
        """Whether the underlying SDK has an active WebSocket session."""
        return self.client is not None and self.client.is_ready

    async def get_user_providers(self) -> List[Dict[str, Any]]:
        """Fetch providers linked to the authenticated user account."""
        if not self.is_ready: return []
        try:
            return await self.client.user.list_providers()
        except Exception as e:
            log.error(f"Error fetching user providers: {e}")
            return []

    async def get_user_info(self) -> Dict[str, Any]:
        """Fetch basic profile info for the current user."""
        if not self.is_ready: return {}
        try:
            return await self.client.user.get_info()
        except Exception as e:
            log.error(f"Error fetching user info: {e}")
            return {}

    async def send_chat_message(self, channel_provider_id: str, message: str, user_provider_id: str):
        """Send a chat message to a specific provider via Synchra."""
        if not self.is_ready: return
        try:
            return await self.client.chat.send_message(channel_provider_id, message, user_provider_id)
        except Exception as e:
            log.error(f"Error sending chat message: {e}")
            return None

    async def broadcast_chat_message(self, channel_id: Union[str, UUID], message: str, user_provider_id: str):
        """Broadcast a chat message to all supported platforms for a channel."""
        if not self.is_ready: return
        try:
            return await self.client.chat.send_message_all(UUID(str(channel_id)), message, user_provider_id)
        except Exception as e:
            log.error(f"Error broadcasting chat message: {e}")
            return None

    async def get_user_info(self):
        """Fetch basic profile info for the authenticated user from Synchra."""
        if not self.is_ready: return None
        try:
            return await self.client.user.get_info()
        except Exception as e:
            log.error(f"Error fetching Synchra user info: {e}")
            return None

    async def list_user_providers(self):
        """Fetch all linked platform providers for the authenticated user."""
        if not self.is_ready: return []
        try:
            return await self.client.user.list_providers()
        except Exception as e:
            log.error(f"Error listing Synchra user providers: {e}")
            return []

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
        """Fallback HLS resolution using yt-dlp."""
        import asyncio
        platform = platform.lower()
        url_map = {
            "twitch": f"https://www.twitch.tv/{handle}",
            "youtube": f"https://www.youtube.com/@{handle}/live",
            "kick": f"https://kick.com/{handle}",
            "tiktok": f"https://www.tiktok.com/@{handle}/live"
        }
        
        target_url = url_map.get(platform)
        if not target_url: return None

        cmd = ["yt-dlp", "-g", "--format", "best", "--no-warnings", target_url]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
            if proc.returncode == 0:
                return stdout.decode().strip()
        except:
            pass
        return None
