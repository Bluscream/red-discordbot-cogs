import asyncio
import logging
import httpx
from typing import Optional, Union, Any, Dict
import discord
from redbot.core.bot import Red
from .session import TwitchLiveSession
from .utils.action_queue import ActionQueue
from .utils.retry import StaggeredRetry
from .utils.formatting import format_status_embed

log = logging.getLogger("red.blu.twitchlive.chat")

class TwitchChatHandler:
    def __init__(self, bot: Red, action_queue: ActionQueue, config: Any):
        self.bot = bot
        self.action_queue = action_queue
        self.config = config
        self._auth_token: Optional[str] = None
        self._token_expires: float = 0

    async def _get_auth_token(self) -> Optional[str]:
        """Gets or refreshes the Twitch OAuth App Token."""
        now = self.bot.loop.time()
        if self._auth_token and now < self._token_expires:
            return self._auth_token
            
        client_id = await self.config.client_id()
        client_secret = await self.config.client_secret()
        
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
                    # Subtrack 60s for safety
                    self._token_expires = now + data["expires_in"] - 60
                    log.info("Twitch OAuth token refreshed successfully.")
                    return self._auth_token
                else:
                    log.error(f"Failed to get Twitch token: {r.status_code} {r.text}")
        except Exception as e:
            log.error(f"Error fetching Twitch token: {e}")
        return None

    async def _get_stream_data(self, username: str) -> Optional[dict]:
        """Fetches live stream info for a user from Twitch Helix API."""
        token = await self._get_auth_token()
        client_id = await self.config.client_id()
        if not token or not client_id:
            return None
            
        url = "https://api.twitch.tv/helix/streams"
        headers = {
            "Authorization": f"Bearer {token}",
            "Client-Id": client_id
        }
        params = {"user_login": username}
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(url, headers=headers, params=params)
                if r.status_code == 200:
                    data = r.json().get("data", [])
                    return data[0] if data else None
                elif r.status_code == 401:
                    # Force token refresh next time
                    self._auth_token = None
                    log.warning(f"Twitch API 401 for {username}, token might be stale.")
        except Exception as e:
            log.error(f"Error checking Twitch status for {username}: {e}")
        return None

    async def _get_user_info(self, username: str) -> Optional[dict]:
        """Fetches general user info (like avatar URL) from Twitch Helix API."""
        token = await self._get_auth_token()
        client_id = await self.config.client_id()
        if not token or not client_id:
            return None
            
        url = "https://api.twitch.tv/helix/users"
        headers = {
            "Authorization": f"Bearer {token}",
            "Client-Id": client_id
        }
        params = {"login": username}
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(url, headers=headers, params=params)
                if r.status_code == 200:
                    data = r.json().get("data", [])
                    return data[0] if data else None
        except Exception as e:
            log.debug(f"Error fetching Twitch user info for {username}: {e}")
        return None

    async def monitor_loop(self, session: TwitchLiveSession):
        """Persistent monitoring loop for Twitch with staggered backoff."""
        retry = StaggeredRetry(start=60.0, multiplier=1.1, max_val=3600.0)
        log.info(f"Started Twitch monitor for {session.username}")
        
        while True:
            try:
                stream = await self._get_stream_data(session.username)
                
                if stream:
                    if not session.is_live:
                        # TRANSITION: Offline -> Online
                        log.info(f"Twitch streamer {session.username} is now LIVE!")
                        session.is_live = True
                        retry.reset()
                        
                        # Populate metadata for identity sync
                        user_info = await self._get_user_info(session.username)
                        if user_info:
                            session.avatar_url = user_info.get("profile_image_url")
                        
                        # Notify Discord
                        embed = format_status_embed(
                            session.username,
                            stream.get("title", ""),
                            game=stream.get("game_name", ""),
                            viewers=stream.get("viewer_count", 0),
                            thumbnail_url=stream.get("thumbnail_url")
                        )
                        await self.action_queue.put({
                            "type": "message",
                            "payload": {"target": session.text_channel, "content": embed}
                        })
                        
                        # Join Voice
                        await self.action_queue.put({
                            "type": "voice_connect",
                            "payload": {"session": session}
                        })
                    
                    # While live, check every 5 minutes
                    await asyncio.sleep(300)
                else:
                    if session.is_live:
                        # TRANSITION: Online -> Offline
                        log.info(f"Twitch streamer {session.username} went offline.")
                        session.is_live = False
                        
                        await self.action_queue.put({
                            "type": "message",
                            "payload": {"target": session.text_channel, "content": f"⚫ **{session.username}** is now offline."}
                        })
                        
                        await self.action_queue.put({
                            "type": "voice_disconnect",
                            "payload": {"session": session}
                        })
                    
                    await retry.sleep()
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Error in Twitch monitor loop ({session.username}): {e}")
                await asyncio.sleep(60)
