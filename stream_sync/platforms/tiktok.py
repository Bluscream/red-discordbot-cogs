import asyncio
import time
from typing import Optional, Dict, Any
from TikTokLive import TikTokLiveClient
from TikTokLive.events import ConnectEvent, LiveEndEvent, DisconnectEvent, RoomUserSeqEvent
from .base import StreamPlatform

class TikTokPlatform(StreamPlatform):
    def __init__(self, bot, action_queue, config):
        super().__init__(bot, action_queue, config)
        self.clients: Dict[str, TikTokLiveClient] = {}
        self.tasks: Dict[str, asyncio.Task] = {}
        self.seen_events = set()

    async def is_live(self, channel_id: str) -> Dict[str, Any]:
        """
        TikTok is best monitored via the client's connection status.
        Status is updated via events.
        """
        return {"live": False}

    async def get_hls_url(self, channel_id: str) -> Optional[str]:
        client = self.clients.get(channel_id)
        if client and client.room_info:
            return client.room_info.get("stream_url", {}).get("hls_pull_url")
        return None

    def _setup_client(self, channel_id: str, session: Any):
        client = TikTokLiveClient(unique_id=f"@{channel_id}")
        self.clients[channel_id] = client

        def log_first_event(event):
            import json
            ename = type(event).__name__
            if ename not in self.seen_events:
                try:
                    # Try raw message to_dict first
                    msg = getattr(event, "_message", None)
                    if msg and hasattr(msg, "to_dict"):
                        data = msg.to_dict()
                    else:
                        data = getattr(event, "to_dict", lambda: {"error": "no to_dict"})()
                    
                    min_json = json.dumps(data, separators=(',', ':'))
                    self.log.info(f"FIRST_EVENT_{ename}: {min_json}")
                    self.seen_events.add(ename)
                except Exception as e:
                    try:
                        self.log.debug(f"to_dict failed for {ename}, using fallback: {e}")
                        data = {k: str(v) for k, v in vars(event).items() if not k.startswith('_')}
                        self.log.info(f"FIRST_EVENT_{ename}_FALLBACK: {json.dumps(data)}")
                        self.seen_events.add(ename)
                    except:
                        self.log.error(f"Failed to dump {ename}: {e}")

        @client.on(ConnectEvent)
        async def on_connect(event: ConnectEvent):
            log_first_event(event)
            self.log.info(f"TikTok Connect: {channel_id} (Room ID: {client.room_id})")
            if not session.is_live:
                session.is_live = True
                await self.on_live_start(session)

        @client.on(RoomUserSeqEvent)
        async def on_user_seq(event: RoomUserSeqEvent):
            """Sync viewer count."""
            log_first_event(event)
            # v6.6.5 uses total_user or viewer_count depending on protocol, total_user is safer
            session.current_viewers = getattr(event, 'total_user', getattr(event, 'viewer_count', 0))

        # --- Debug Event Listeners ---
        @client.on("event")
        async def on_any_event(event):
            log_first_event(event)

        @client.on(LiveEndEvent)
        async def on_live_end(event: LiveEndEvent):
            log_first_event(event)
            self.log.info(f"TikTok LiveEnd: {channel_id}")
            session.is_live = False
            session.last_live = time.time()
            async with self.config.monitored_streams() as ms:
                if "tiktok" in ms and channel_id in ms["tiktok"]:
                    ms["tiktok"][channel_id]["last_live"] = session.last_live
            await self.on_live_end(session)

        @client.on(DisconnectEvent)
        async def on_disconnect(event: DisconnectEvent):
            self.log.info(f"TikTok Disconnect: {channel_id}")

        return client

    async def start_monitor(self, session: Any):
        """Start the TikTok monitor in a managed background task."""
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
                self.log.debug(f"TikTok user @{channel_id} is offline. Polling...")
                await asyncio.sleep(60)
            except UserNotFoundError:
                self.log.error(f"TikTok user @{channel_id} not found. Stopping monitor.")
                break
            except asyncio.CancelledError:
                self.log.info(f"TikTok monitor task for @{channel_id} cancelled.")
                break
            except Exception as e:
                err_str = str(e)
                # If we're not authenticated yet and we hit a block/error that looks like it needs auth
                if not authenticated and session_id and ("BLOCK" in err_str or "AUTHENTICATED" in err_str or "SIGN_SERVER" in err_str):
                    self.log.warning(f"TikTok guest connection blocked for @{channel_id}. Retrying with authentication...")
                    try:
                        client.web.set_session(session_id, tt_target_idc)
                        authenticated = True
                        continue # Retry immediately with auth
                    except Exception as ae:
                        self.log.error(f"Failed to apply TikTok session for @{channel_id}: {ae}")
                
                self.log.error(f"Unexpected TikTok error for @{channel_id}: {e}")
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
