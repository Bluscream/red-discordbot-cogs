import asyncio
import logging
import httpx
import re
import json
import time
from typing import Optional, Dict, Any, List
from .base import StreamPlatform

class YoutubeChatScraper:
    """A resilient, dependency-free YouTube Live Chat scraper/sync service."""
    def __init__(self, platform, session):
        self.platform = platform
        self.session = session
        self.log = platform.log
        self.task: Optional[asyncio.Task] = None
        self._running = False
        self._continuation: Optional[str] = None
        self._innertube_key: Optional[str] = None
        self._cookies = {"CONSENT": "YES+cb.20210420-15-p1.en-GB+FX+634"}
        self._headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9"
        }

    async def start(self):
        self._running = True
        self.task = asyncio.create_task(self._run_loop())

    async def stop(self):
        self._running = False
        if self.task:
            self.task.cancel()

    async def _fetch_initial(self) -> bool:
        """Find the initial continuation token and API key from the video page."""
        url = self.session.hls_url or f"https://www.youtube.com/{self.session.channel_id}/live"
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                r = await client.get(url, headers=self._headers, cookies=self._cookies)
                if r.status_code != 200: return False
                
                html = r.text
                
                # Extract InnerTube API Key
                key_match = re.search(r'"INNERTUBE_API_KEY":"(.*?)"', html)
                if key_match: self._innertube_key = key_match.group(1)
                
                # Extract Continuation Token
                cont_match = re.search(r'"continuation":"(.*?)"', html)
                if cont_match: self._continuation = cont_match.group(1)
                
                return bool(self._innertube_key and self._continuation)
        except Exception as e:
            self.log.error(f"YouTube chat initial fetch error: {e}")
        return False

    async def _run_loop(self):
        if not await self._fetch_initial():
            self.log.warning(f"Could not initialize YouTube chat for {self.session.channel_id}.")
            return

        while self._running:
            try:
                url = f"https://www.youtube.com/youtubei/v1/live_chat/get_live_chat?key={self._innertube_key}"
                payload = {
                    "context": {
                        "client": {
                            "clientName": "WEB",
                            "clientVersion": "2.20210622.10.00"
                        }
                    },
                    "continuation": self._continuation
                }
                
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.post(url, json=payload, headers=self._headers, cookies=self._cookies)
                    if r.status_code != 200:
                        await asyncio.sleep(10)
                        continue
                        
                    data = r.json()
                    
                    # Update Continuation for next poll
                    cont_data = data.get("continuationContents", {}).get("liveChatContinuation", {}).get("continuations", [])
                    if cont_data:
                        self._continuation = cont_data[0].get("invalidationContinuationData", {}).get("continuation") or \
                                            cont_data[0].get("timedContinuationData", {}).get("continuation")
                    
                    # Process actions
                    actions = data.get("continuationContents", {}).get("liveChatContinuation", {}).get("actions", [])
                    for action in actions:
                        item = action.get("addChatItemAction", {}).get("item", {}).get("liveChatTextMessageRenderer")
                        if item:
                            author = item.get("authorName", {}).get("simpleText", "Unknown")
                            message_runs = item.get("message", {}).get("runs", [])
                            message_text = "".join([r.get("text", "") for r in message_runs])
                            
                            if message_text:
                                await self.platform.action_queue.put({
                                    "type": "chat_message",
                                    "payload": {
                                        "platform": "youtube",
                                        "channel_id": self.session.channel_id,
                                        "author": author,
                                        "message": message_text,
                                        "target": self.session.text_channel,
                                        "session": self.session
                                    }
                                })
                
                await asyncio.sleep(5) # Poll every 5s
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.log.error(f"YouTube chat poll error: {e}")
                await asyncio.sleep(15)

class YoutubePlatform(StreamPlatform):
    def __init__(self, bot, action_queue, config):
        super().__init__(bot, action_queue, config)
        self.chat_scrapers: Dict[str, YoutubeChatScraper] = {}

    async def is_live(self, channel_id: str) -> Dict[str, Any]:
        url = f"https://www.youtube.com/channel/{channel_id}/live"
        if channel_id.startswith("@"):
            url = f"https://www.youtube.com/{channel_id}/live"
            
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9"
        }
        
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                cookies = {"CONSENT": "YES+cb.20210420-15-p1.en-GB+FX+634"}
                r = await client.get(url, headers=headers, cookies=cookies)
                
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
                    try:
                        viewers = int(viewers_match.group(1).replace(",", ""))
                    except:
                        pass
                
                return {
                    "live": True, 
                    "title": title, 
                    "viewers": viewers,
                    "thumbnail": f"https://i.ytimg.com/vi/{channel_id}/maxresdefault.jpg" # Generic guess
                }
                
        except Exception as e:
            self.log.error(f"Youtube check error for {channel_id}: {e}")
        return {"live": False}

    async def get_hls_url(self, channel_id: str) -> Optional[str]:
        if channel_id.startswith("@"):
            return f"https://www.youtube.com/{channel_id}/live"
        return f"https://www.youtube.com/channel/{channel_id}/live"

    async def start_chat(self, session: Any):
        if session.channel_id not in self.chat_scrapers:
            scraper = YoutubeChatScraper(self, session)
            self.chat_scrapers[session.channel_id] = scraper
            await scraper.start()

    async def stop_chat(self, channel_id: str):
        if channel_id in self.chat_scrapers:
            await self.chat_scrapers[channel_id].stop()
            del self.chat_scrapers[channel_id]
