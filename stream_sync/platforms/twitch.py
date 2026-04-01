import asyncio
import logging
import httpx
import twitchio
from typing import Optional, Dict, Any, List
from .base import StreamPlatform

class TwitchChatBridge(twitchio.Client):
    """A robust Twitch chat bridge using the TwitchIO library."""
    def __init__(self, platform, session, token):
        super().__init__(token=token, initial_channels=[session.channel_id.lower().replace('@', '')])
        self.platform = platform
        self.session = session
        self.log = platform.log
        self.task: Optional[asyncio.Task] = None

    async def event_ready(self):
        self.log.info(f"TwitchIO Bridge Ready: {self.nick} in #{self.session.channel_id}")

    async def event_message(self, message):
        """Standardized message handler for chat synchronization."""
        if message.echo: return
        
        await self.platform.action_queue.put({
            "type": "chat_message",
            "payload": {
                "platform": "twitch",
                "channel_id": self.session.channel_id,
                "author": message.author.name,
                "message": message.content,
                "target": self.session.text_channel,
                "session": self.session
            }
        })

    def start(self):
        self.task = asyncio.create_task(self.connect())

    async def stop(self):
        await self.close()
        if self.task: self.task.cancel()

class TwitchPlatform(StreamPlatform):
    def __init__(self, bot, action_queue, config):
        super().__init__(bot, action_queue, config)
        self._auth_token: Optional[str] = None
        self._token_expires: float = 0
        self.chat_bridges: Dict[str, TwitchChatBridge] = {}

    async def _get_auth_token(self) -> Optional[str]:
        now = self.bot.loop.time()
        if self._auth_token and now < self._token_expires:
            return self._auth_token
            
        client_id = await self.config.twitch_client_id()
        client_secret = await self.config.twitch_client_secret()
        
        if not client_id or not client_secret:
            return None
            
        url = "https://id.twitch.tv/oauth2/token"
        params = {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials"
        }
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(url, params=params)
                if r.status_code == 200:
                    data = r.json()
                    self._auth_token = data["access_token"]
                    self._token_expires = now + data["expires_in"] - 60
                    return self._auth_token
        except Exception as e:
            self.log.error(f"Twitch token error: {e}")
        return None

    async def is_live(self, channel_id: str) -> Dict[str, Any]:
        token = await self._get_auth_token()
        client_id = await self.config.twitch_client_id()
        if not token or not client_id:
            return {"live": False}
            
        url = "https://api.twitch.tv/helix/streams"
        headers = {"Authorization": f"Bearer {token}", "Client-Id": client_id}
        params = {"user_login": channel_id.lower().replace("@", "")}
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(url, headers=headers, params=params)
                if r.status_code == 200:
                    data = r.json().get("data", [])
                    if data:
                        stream = data[0]
                        return {
                            "live": True,
                            "title": stream.get("title", "Live"),
                            "viewers": stream.get("viewer_count", 0),
                            "thumbnail": stream.get("thumbnail_url"),
                            "extra": stream.get("game_name", "")
                        }
        except Exception as e:
            self.log.error(f"Twitch check error for {channel_id}: {e}")
        return {"live": False}

    async def get_metadata(self, channel_id: str) -> Dict[str, Any]:
        token = await self._get_auth_token()
        client_id = await self.config.twitch_client_id()
        if not token or not client_id:
            return {}
            
        url = "https://api.twitch.tv/helix/users"
        headers = {"Authorization": f"Bearer {token}", "Client-Id": client_id}
        params = {"login": channel_id.lower().replace("@", "")}
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(url, headers=headers, params=params)
                if r.status_code == 200:
                    data = r.json().get("data", [])
                    if data:
                        user = data[0]
                        return {"avatar_url": user.get("profile_image_url")}
        except Exception as e:
            self.log.debug(f"Twitch metadata error for {channel_id}: {e}")
        return {}

    async def get_hls_url(self, channel_id: str) -> Optional[str]:
        return f"https://www.twitch.tv/{channel_id.lower().replace('@', '')}"

    async def start_chat(self, session: Any):
        token = await self.config.twitch_irc_password()
        
        if not token:
            self.log.warning("Twitch IRC token (oauth:...) not set. Chat synchronization disabled.")
            return

        if session.channel_id not in self.chat_bridges:
            bridge = TwitchChatBridge(self, session, token)
            self.chat_bridges[session.channel_id] = bridge
            bridge.start()

    async def stop_chat(self, channel_id: str):
        if channel_id in self.chat_bridges:
            await self.chat_bridges[channel_id].stop()
            del self.chat_bridges[channel_id]
