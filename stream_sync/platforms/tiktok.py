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

        @client.on(ConnectEvent)
        async def on_connect(event: ConnectEvent):
            self.log.info(f"TikTok Connect: {channel_id}")
            if not session.is_live:
                session.is_live = True
                await self.on_live_start(session)

        @client.on(RoomUserSeqEvent)
        async def on_user_seq(event: RoomUserSeqEvent):
            """Sync viewer count."""
            session.current_viewers = event.viewer_count

        @client.on(LiveEndEvent)
        async def on_live_end(event: LiveEndEvent):
            self.log.info(f"TikTok LiveEnd: {channel_id}")
            session.is_live = False
            session.last_live = time.time()
            # Persist last_live
            async with self.config.monitored_streams() as ms:
                if "tiktok" in ms and channel_id in ms["tiktok"]:
                    ms["tiktok"][channel_id]["last_live"] = session.last_live
            
            await self.on_live_end(session)

        @client.on(DisconnectEvent)
        async def on_disconnect(event: DisconnectEvent):
            self.log.info(f"TikTok Disconnect: {channel_id}")

        return client

    async def start_monitor(self, session: Any):
        client = self._setup_client(session.channel_id, session)
        # Avoid blocking the main thread
        asyncio.create_task(client.run())

    async def stop_monitor(self, channel_id: str):
        client = self.clients.get(channel_id)
        if client:
            await client.stop()
            del self.clients[channel_id]
