import asyncio
import logging
import httpx
import twitchio
from typing import Optional, Dict, Any, List
from .base import StreamPlatform

class TwitchChatBridge(twitchio.Client):
    """A robust Twitch chat bridge using the TwitchIO library (v3.x EventSub)."""
    def __init__(self, platform, session, token, client_id, client_secret, broadcaster_id, bot_id):
        # We don't pass token here, we pass it to .start()
        super().__init__(client_id=client_id, client_secret=client_secret, bot_id=bot_id)
        self.token = token
        self.platform = platform
        self.session = session
        self.broadcaster_id = broadcaster_id
        self.log = platform.log
        self.task: Optional[asyncio.Task] = None
        self._save_tokens = False # Fix PermissionError: .tio.tokens.json

    async def setup_hook(self):
        """Called by twitchio.Client once logged in."""
        try:
            # Add the user token to the ManagedHTTPClient for EventSub
            clean_token = self.token.replace("oauth:", "")
            await self.http.add_token(clean_token, "") # refresh token empty for now
            
            # Subscribe to chat messages for the target broadcaster using EventSub v3
            from twitchio.eventsub import ChatMessageSubscription
            # self.bot_id is already a property from super()
            payload = ChatMessageSubscription(broadcaster_user_id=self.broadcaster_id, user_id=self.bot_id)
            await self.subscribe_websocket(payload, as_bot=True)
            self.log.info(f"TwitchIO EventSub: Subscribed to chat for {self.session.channel_id} (ID: {self.broadcaster_id})")
        except Exception as e:
            self.log.error(f"TwitchIO subscription error for {self.session.channel_id}: {e}")

    async def event_ready(self):
        name = self.user.name if self.user else "Bot"
        self.log.info(f"TwitchIO Bridge Ready: {name} monitoring #{self.session.channel_id}")

    async def event_chat_message(self, payload):
        """Standardized message handler for chat synchronization (v3.x)."""
        # payload is a ChatMessagePayload object
        if payload.chatter.id == self.bot_id: return
        
        await self.platform.action_queue.put({
            "type": "chat_message",
            "payload": {
                "platform": "twitch",
                "channel_id": self.session.channel_id,
                "author": payload.chatter.name,
                "message": payload.message.text,
                "target": self.session.text_channel,
                "session": self.session
            }
        })

    def run_bridge(self):
        """Starts the TwitchIO client in a background task."""
        self.task = asyncio.create_task(super().start(token=self.token))

    async def stop(self):
        # Pass save_tokens=False as a fail-safe to prevent PermissionError on close
        await self.close(save_tokens=False)
        if self.task: self.task.cancel()

class TwitchPlatform(StreamPlatform):
    def __init__(self, bot, action_queue, config, cog):
        super().__init__(bot, action_queue, config, cog)
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
        url = f"https://www.twitch.tv/{channel_id.lower().replace('@', '')}"
        return await self._get_hls_via_ytdlp(url)

    async def start_chat(self, session: Any):
        token = await self.config.twitch_irc_password()
        client_id = await self.config.twitch_client_id()
        client_secret = await self.config.twitch_client_secret()
        
        if not token or not client_id or not client_secret:
            self.log.warning("Twitch credentials (ID, Secret, or Token) missing. Chat disabled.")
            return

        if session.channel_id not in self.chat_bridges:
            # Resolve Broadcaster and Bot IDs
            try:
                # Helper for helix requests
                auth_token = await self._get_auth_token()
                headers = {"Authorization": f"Bearer {auth_token}", "Client-Id": client_id}
                
                async with httpx.AsyncClient(timeout=10.0) as client:
                    # Get Broadcaster ID
                    br_r = await client.get("https://api.twitch.tv/helix/users", headers=headers, params={"login": session.channel_id.lower()})
                    if br_r.status_code != 200: raise Exception(f"Failed to get broadcaster ID: {br_r.text}")
                    broadcaster_id = br_r.json()["data"][0]["id"]
                    
                    # Get Bot ID (using the user's token)
                    # We need to validate the token to get the user ID
                    bot_r = await client.get("https://id.twitch.tv/oauth2/validate", headers={"Authorization": f"OAuth {token.replace('oauth:', '')}"})
                    if bot_r.status_code != 200:
                        self.log.error(f"Twitch token validation failed (401). Please refresh your chatbot token using: [p]streamset twitchchat <nick> <token>")
                        raise Exception(f"Invalid Twitch chatbot token: {bot_r.text}")
                    bot_id = bot_r.json()["user_id"]
                    
                bridge = TwitchChatBridge(self, session, token, client_id, client_secret, broadcaster_id, bot_id)
                self.chat_bridges[session.channel_id] = bridge
                bridge.run_bridge()
            except Exception as e:
                self.log.error(f"Failed to start Twitch chat for {session.channel_id}: {e}")

    async def stop_chat(self, channel_id: str):
        if channel_id in self.chat_bridges:
            await self.chat_bridges[channel_id].stop()
            del self.chat_bridges[channel_id]
