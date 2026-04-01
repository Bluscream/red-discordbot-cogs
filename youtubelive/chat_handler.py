import asyncio
import logging
import httpx
import re
from typing import Optional, Union, Any
import discord
from redbot.core.bot import Red
from .session import YouTubeLiveSession
from .utils.action_queue import ActionQueue
from .utils.retry import StaggeredRetry
from .utils.formatting import format_status_embed

log = logging.getLogger("red.blu.youtubelive.chat")

class YouTubeChatHandler:
    def __init__(self, bot: Red, action_queue: ActionQueue):
        self.bot = bot
        self.action_queue = action_queue
        # Internal map for session cleanup
        self._loop_tasks = {}

    async def _is_live(self, channel_id: str) -> dict:
        """
        Polls YouTube to check if a channel is live.
        Returns a dict with 'live' (bool), 'title' (str), and 'viewers' (int).
        """
        url = f"https://www.youtube.com/channel/{channel_id}/live"
        if channel_id.startswith("@"):
            url = f"https://www.youtube.com/{channel_id}/live"
            
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9"
        }
        
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                # Add a dummy consent cookie to bypass generic walls
                cookies = {"CONSENT": "YES+cb.20210420-15-p1.en-GB+FX+634"}
                r = await client.get(url, headers=headers, cookies=cookies)
                
                if r.status_code != 200:
                    return {"live": False}
                
                html = r.text
                
                # Check for live indicator
                # YouTube often embeds JSON in 'ytInitialData'
                is_live = '"style":"LIVE"' in html or '{"text":" watching"}' in html or '"isLive":true' in html
                
                if not is_live:
                    return {"live": False}
                
                # Try to extract title
                title = "Live Stream"
                title_match = re.search(r'<title>(.*?) - YouTube</title>', html)
                if title_match:
                    title = title_match.group(1)
                
                # Try to extract viewers
                viewers = 0
                viewers_match = re.search(r'"viewCount":\{"runs":\[\{"text":"([\d,]+)"\}', html)
                if viewers_match:
                    try:
                        viewers = int(viewers_match.group(1).replace(",", ""))
                    except:
                        pass
                
                return {"live": True, "title": title, "viewers": viewers}
                
        except Exception as e:
            log.error(f"Error checking YT status for {channel_id}: {e}")
            return {"live": False}

    async def monitor_loop(self, session: YouTubeLiveSession):
        """
        Persistent monitoring loop with staggered backoff.
        """
        retry = StaggeredRetry(start=60.0, multiplier=1.05, max_val=1800.0) # More aggressive than TikTok for YT
        
        log.info(f"Started monitoring loop for YouTube channel: {session.channel_id}")
        
        while True:
            try:
                status = await self._is_live(session.channel_id)
                
                if status.get("live"):
                    if not session.is_live:
                        # TRANSITION: Offline -> Online
                        log.info(f"YouTube channel {session.channel_id} is now LIVE!")
                        session.is_live = True
                        retry.reset()
                        
                        # Notify Discord
                        embed = format_status_embed(
                            session.channel_id, 
                            status.get("title", ""), 
                            status.get("viewers", 0)
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
                    
                    # While live, check every 5 minutes for status changes/disconnects
                    await asyncio.sleep(300)
                else:
                    if session.is_live:
                        # TRANSITION: Online -> Offline
                        log.info(f"YouTube channel {session.channel_id} went offline.")
                        session.is_live = False
                        
                        # Notify Discord
                        await self.action_queue.put({
                            "type": "message",
                            "payload": {"target": session.text_channel, "content": f"⚫ **{session.channel_id}** is now offline."}
                        })
                        
                        # Disconnect Voice
                        await self.action_queue.put({
                            "type": "voice_disconnect",
                            "payload": {"session": session}
                        })
                    
                    # Backoff while offline
                    await retry.sleep()
                    
            except asyncio.CancelledError:
                log.info(f"Monitoring loop for {session.channel_id} cancelled.")
                break
            except Exception as e:
                log.error(f"Error in YT monitor loop ({session.channel_id}): {e}")
                await asyncio.sleep(60)
