import asyncio
import time
from typing import Optional, Dict, Any
from TikTokLive import TikTokLiveClient
from TikTokLive.events import ConnectEvent, LiveEndEvent, DisconnectEvent, RoomUserSeqEvent, CommentEvent
from .base import StreamPlatform

class TikTokPlatform(StreamPlatform):
    def __init__(self, bot, action_queue, config, cog):
        super().__init__(bot, action_queue, config, cog)
        self.clients: Dict[str, TikTokLiveClient] = {}
        self.tasks: Dict[str, asyncio.Task] = {}

    async def is_live(self, channel_id: str) -> Dict[str, Any]:
        """
        TikTok is best monitored via the client's connection status.
        Status is updated via events.
        """
        return {"live": False}

    async def get_hls_url(self, channel_id: str) -> Optional[str]:
        client = self.clients.get(channel_id)
        if client and client.room_info:
            hls = client.room_info.get("stream_url", {}).get("hls_pull_url")
            if hls: return hls
        
        # Fallback to yt-dlp if client room_info is missing
        return await self._get_hls_via_ytdlp(f"https://www.tiktok.com/@{channel_id}/live")

    def _setup_client(self, channel_id: str, session: Any):
        client = TikTokLiveClient(unique_id=f"@{channel_id}")
        self.clients[channel_id] = client

        def log_event(event):
            import json
            ename = type(event).__name__
            try:
                # Try raw message to_dict first
                msg = getattr(event, "_message", None)
                if msg and hasattr(msg, "to_dict"):
                    data = msg.to_dict()
                else:
                    data = getattr(event, "to_dict", lambda: {"error": "no to_dict"})()
                
                min_json = json.dumps(data, separators=(',', ':'))
                self.log.info(f"[TikTok Event] #{channel_id} | {ename}: {min_json}")
            except Exception as e:
                try:
                    self.log.debug(f"to_dict failed for {ename}, using fallback: {e}")
                    data = {k: str(v) for k, v in vars(event).items() if not k.startswith('_')}
                    self.log.info(f"[TikTok Event] #{channel_id} | {ename} (Fallback): {json.dumps(data)}")
                except:
                    self.log.error(f"Failed to dump {ename}: {e}")

        @client.on(ConnectEvent)
        async def on_connect(event: ConnectEvent):
            log_event(event)
            self.log.info(f"TikTok Connect: {channel_id} (Room ID: {client.room_id})")
            if not session.is_live:
                # Prepare status dict for unified handler
                info = client.room_info or {}
                status = {
                    "live": True,
                    "title": info.get("title", "TikTok Live"),
                    "viewers": info.get("stats", {}).get("viewer_count", 0),
                    "thumbnail": info.get("owner", {}).get("avatar_large")
                }
                await self.cog._handle_go_live(self.name, channel_id, status)
            
            # Reset the backoff on successful connection
            if hasattr(session, 'retry'):
                session.retry.reset()

        @client.on(CommentEvent)
        async def on_comment(event: CommentEvent):
            """Sync TikTok chat to Discord."""
            log_event(event)
            self.log.info(f"[TikTok Chat] #{channel_id} | {event.user.nickname}: {event.comment}")
            
            await self.action_queue.put({
                "type": "chat_message",
                "payload": {
                    "platform": "tiktok",
                    "channel_id": channel_id,
                    "author": event.user.nickname,
                    "message": event.comment,
                    "target": session.text_channel,
                    "session": session
                }
            })

        @client.on(RoomUserSeqEvent)
        async def on_user_seq(event: RoomUserSeqEvent):
            """Sync viewer count."""
            log_event(event)
            # v6.6.5 uses total_user or viewer_count depending on protocol, total_user is safer
            session.current_viewers = getattr(event, 'total_user', getattr(event, 'viewer_count', 0))

        # --- Debug Event Listeners ---
        @client.on("any") # Some TikTokLive versions use "any"
        async def on_any_event_alt(event):
            log_event(event)

        @client.on("event")
        async def on_any_event(event):
            log_event(event)

        @client.on(LiveEndEvent)
        async def on_live_end(event: LiveEndEvent):
            log_event(event)
            self.log.info(f"TikTok LiveEnd: {channel_id}")
            if session.is_live:
                await self.cog._handle_go_offline(self.name, channel_id)

        @client.on(DisconnectEvent)
        async def on_disconnect(event: DisconnectEvent):
            self.log.info(f"TikTok Disconnect: {channel_id}")

        return client

    async def start_monitor(self, session: Any, retry: Optional[Any] = None):
        """Start the TikTok monitor in a managed background task."""
        if retry: session.retry = retry
        self.log.info(f"Spawning background monitor for TikTok user @{session.channel_id}...")
        task = asyncio.create_task(self._run_client_safely(session))
        self.tasks[session.channel_id] = task
        session.monitor_task = task # For UI/State tracking

    async def _run_client_safely(self, session: Any):
        from TikTokLive.client.errors import UserOfflineError, UserNotFoundError
        
        channel_id = session.channel_id
        client = self._setup_client(channel_id, session)
        
        # Pull credentials from config
        session_id = await self.config.tiktok_session_id()
        tt_target_idc = await self.config.tiktok_tt_target_idc()
        
        authenticated = False
        
        while True:
            try:
                # Attempt 1: Guest (or whatever the client state is)
                await client.start()
            except UserOfflineError:
                self.log.info(f"TikTok user @{channel_id} is currently offline. Backing off...")
                if retry:
                    await retry.sleep()
                else:
                    await asyncio.sleep(60)
            except UserNotFoundError:
                self.log.error(f"TikTok user @{channel_id} not found. Please check the spelling.")
                break
            except asyncio.CancelledError:
                self.log.info(f"TikTok monitor task for @{channel_id} cancelled.")
                break
            except Exception as e:
                err_str = str(e)
                self.log.error(f"TikTok connection error for @{channel_id}: {err_str}")
                # If we're not authenticated yet and we hit a block/error that looks like it needs auth
                if not authenticated and session_id and ("BLOCK" in err_str or "AUTHENTICATED" in err_str or "SIGN_SERVER" in err_str or "room_id" in err_str.lower()):
                    self.log.warning(f"TikTok guest connection blocked for @{channel_id}. Retrying with session_id...")
                    try:
                        client.web.set_session(session_id, tt_target_idc)
                        authenticated = True
                        continue # Retry immediately with auth
                    except Exception as ae:
                        self.log.error(f"Failed to apply TikTok session for @{channel_id}: {ae}")
                
                # Standard staggered backoff for other errors
                self.log.error(f"Unexpected TikTok error for @{channel_id}: {e}")
                if hasattr(session, 'retry'):
                    await session.retry.sleep()
                else:
                    await asyncio.sleep(120)
            
            # If the loop naturally completes (rare for client.start() unless it disconnects)
            # we check if we should still be running.
            if not self.tasks.get(channel_id): break

    async def stop_monitor(self, channel_id: str):
        """Stop the TikTok monitor and clean up resources."""
        task = self.tasks.get(channel_id)
        if task:
            task.cancel()
            del self.tasks[channel_id]

        client = self.clients.get(channel_id)
        if client:
            try:
                await client.stop()
            except:
                pass
            del self.clients[channel_id]
