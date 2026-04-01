import asyncio
import logging
import httpx
import re
import ssl
from typing import Optional, Dict, Any, List
from .base import StreamPlatform

class TwitchIRCClient:
    """A lightweight, dependency-free Twitch IRC client for chat synchronization."""
    def __init__(self, platform, session):
        self.platform = platform
        self.session = session
        self.log = platform.log
        self.task: Optional[asyncio.Task] = None
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self._running = False

    async def start(self, nick: str, password: str):
        self._running = True
        self.task = asyncio.create_task(self._run_loop(nick, password))

    async def stop(self):
        self._running = False
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except: pass
        if self.task:
            self.task.cancel()

    async def _run_loop(self, nick: str, password: str):
        channel = f"#{self.session.channel_id.lower().replace('@', '')}"
        
        while self._running:
            try:
                # Use SSL for security
                ctx = ssl.create_default_context()
                self.reader, self.writer = await asyncio.open_connection(
                    "irc.chat.twitch.tv", 6697, ssl=ctx
                )
                
                # Authenticate
                self.writer.write(f"PASS {password}\r\n".encode())
                self.writer.write(f"NICK {nick}\r\n".encode())
                self.writer.write(f"JOIN {channel}\r\n".encode())
                await self.writer.drain()
                
                self.log.info(f"Connected to Twitch IRC for {channel}")
                
                while self._running:
                    line = await self.reader.readline()
                    if not line: break
                    line = line.decode().strip()
                    
                    if line.startswith("PING"):
                        self.writer.write(f"PONG {line.split()[1]}\r\n".encode())
                        await self.writer.drain()
                        continue
                        
                    # Basic PRIVMSG parsing
                    # :user!user@user.tmi.twitch.tv PRIVMSG #channel :message
                    match = re.search(r"^:(\w+)!.*PRIVMSG #\w+ :(.*)$", line)
                    if match:
                        user, text = match.groups()
                        # Push to action queue
                        await self.platform.action_queue.put({
                            "type": "chat_message",
                            "payload": {
                                "platform": "twitch",
                                "channel_id": self.session.channel_id,
                                "author": user,
                                "message": text,
                                "target": self.session.text_channel,
                                "session": self.session
                            }
                        })
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.log.error(f"Twitch IRC error for {channel}: {e}")
                await asyncio.sleep(10) # Reconnect backoff

class TwitchPlatform(StreamPlatform):
    def __init__(self, bot, action_queue, config):
        super().__init__(bot, action_queue, config)
        self._auth_token: Optional[str] = None
        self._token_expires: float = 0
        self.chat_clients: Dict[str, TwitchIRCClient] = {}

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
        nick = await self.config.twitch_irc_nick()
        password = await self.config.twitch_irc_password()
        
        if not nick or not password:
            self.log.warning("Twitch IRC credentials not set. Chat synchronization disabled.")
            return

        if session.channel_id not in self.chat_clients:
            client = TwitchIRCClient(self, session)
            self.chat_clients[session.channel_id] = client
            await client.start(nick, password)

    async def stop_chat(self, channel_id: str):
        if channel_id in self.chat_clients:
            await self.chat_clients[channel_id].stop()
            del self.chat_clients[channel_id]
