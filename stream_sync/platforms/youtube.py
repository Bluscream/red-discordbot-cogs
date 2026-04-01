import asyncio
import logging
import httpx
import re
import pytchat
from typing import Optional, Dict, Any, List
from .base import StreamPlatform

class YoutubeChatBridge:
    """A robust YouTube live chat bridge using the pytchat library."""
    def __init__(self, platform, session):
        self.platform = platform
        self.session = session
        self.log = platform.log
        self.task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        self._running = True
        # Extracts video_id from channel_id or uses channel_id if it's already a video_id
        # (Though usually we want to find the current live video ID)
        video_id = await self._find_video_id()
        if not video_id:
            self.log.warning(f"Could not find live video ID for YouTube channel {self.session.channel_id}")
            return

        self.task = asyncio.create_task(self._run_loop(video_id))

    async def _find_video_id(self) -> Optional[str]:
        """Fetch the channel's live page to extract the current video ID."""
        url = f"https://www.youtube.com/channel/{self.session.channel_id}/live"
        if self.session.channel_id.startswith("@"):
            url = f"https://www.youtube.com/{self.session.channel_id}/live"
            
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                r = await client.get(url)
                if r.status_code == 200:
                    match = re.search(r'\"videoDetails\":{\"videoId\":\"(.*?)\"', r.text)
                    if match: return match.group(1)
        except Exception as e:
            self.log.error(f"YouTube video ID lookup error: {e}")
        return None

    async def _run_loop(self, video_id: str):
        try:
            chat = pytchat.create(video_id=video_id)
            while chat.is_alive() and self._running:
                async for c in chat.get().async_items():
                    if not self._running: break
                    
                    await self.platform.action_queue.put({
                        "type": "chat_message",
                        "payload": {
                            "platform": "youtube",
                            "channel_id": self.session.channel_id,
                            "author": c.author.name,
                            "message": c.message,
                            "target": self.session.text_channel,
                            "session": self.session
                        }
                    })
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.log.error(f"Pytchat error for {video_id}: {e}")

    async def stop(self):
        self._running = False
        if self.task:
            self.task.cancel()

class YoutubePlatform(StreamPlatform):
    def __init__(self, bot, action_queue, config, cog):
        super().__init__(bot, action_queue, config, cog)
        self.chat_bridges: Dict[str, YoutubeChatBridge] = {}

    async def is_live(self, channel_id: str) -> Dict[str, Any]:
        url = f"https://www.youtube.com/channel/{channel_id}/live"
        if channel_id.startswith("@"):
            url = f"https://www.youtube.com/{channel_id}/live"
            
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9"
        }
        
        try:
            cookies = {"CONSENT": "YES+cb.20210420-15-p1.en-GB+FX+634"}
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, cookies=cookies) as client:
                r = await client.get(url, headers=headers)
                
                if r.status_code != 200:
                    return {"live": False}
                
                html = r.text
                is_live = '"style":"LIVE"' in html or '{"text":" watching"}' in html or '"isLive":true' in html
                
                if not is_live:
                    return {"live": False}
                
                title = "Live Stream"
                title_match = re.search(r'<title>(.*?) - YouTube</title>', html)
                if title_match:
                    title = title_match.group(1)
                
                viewers = 0
                viewers_match = re.search(r'"viewCount":\{"runs":\[\{"text":"([\d,]+)"\}', html)
                if viewers_match:
                    try: voters = viewers_match.group(1).replace(",", "")
                    except: voters = "0"
                
                thumbnail = f"https://i.ytimg.com/vi/{channel_id}/maxresdefault.jpg"
                
                # If we have @handle, we can't easily guess the thumbnail without a video_ID
                # yt-dlp will help us get the real video_ID and thumbnail later during HLS extraction
                
                return {
                    "live": True, 
                    "title": title, 
                    "viewers": int(voters) if voters.isdigit() else 0,
                    "thumbnail": thumbnail
                }
                
        except Exception as e:
            self.log.error(f"Youtube check error for {channel_id}: {e}")
        return {"live": False}

    async def get_hls_url(self, channel_id: str) -> Optional[str]:
        url = f"https://www.youtube.com/channel/{channel_id}/live"
        if channel_id.startswith("@"):
            url = f"https://www.youtube.com/{channel_id}/live"
        return await self._get_hls_via_ytdlp(url)

    async def start_chat(self, session: Any):
        if session.channel_id not in self.chat_bridges:
            bridge = YoutubeChatBridge(self, session)
            self.chat_bridges[session.channel_id] = bridge
            await bridge.start()

    async def stop_chat(self, channel_id: str):
        if channel_id in self.chat_bridges:
            await self.chat_bridges[channel_id].stop()
            del self.chat_bridges[channel_id]
