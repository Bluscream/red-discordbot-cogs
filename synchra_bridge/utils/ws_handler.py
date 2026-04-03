import logging
import asyncio
from typing import Dict, Any, Callable, Optional, Set
from uuid import UUID
from .retry import StaggeredRetry

class SynchraWSHandler:
    """Manages Synchra WebSocket connection and dispatches events to the cog."""
    
    def __init__(self, api_manager, action_queue):
        self.api = api_manager
        self.action_queue = action_queue
        self.log = logging.getLogger("red.blu.synchra_bridge.ws")
        self._running = False
        self._subscriptions: Set[UUID] = set()

    async def start(self):
        """Start the WebSocket client and register handlers."""
        if not self.api.is_ready:
            self.log.warning("API Manager not ready. WebSocket not started.")
            return

        if self._running:
            return

        self._running = True
        
        # Register permanent handlers
        @self.api.client.ws.on("activity")
        async def on_activity(event): await self._handle_activity(event)

        @self.api.client.ws.on("chat_message")
        async def on_chat(event): await self._handle_chat(event)

        @self.api.client.ws.on("status")
        async def on_status(event): await self._handle_status(event)

        @self.api.client.ws.on("connect")
        async def on_connect():
            self.log.info("Synchra WebSocket session authorized and ready.")
                
        @self.api.client.ws.on("disconnect")
        async def on_disconnect():
            self.log.warning("Synchra WebSocket disconnected.")

        # Let the SDK handle the connection and its own internal reconnection
        try:
            await self.api.client.connect()
            self.log.info("Synchra WebSocket connection initiated.")
        except Exception as e:
            self.log.error(f"Failed to initiate Synchra WS connection: {e}")

    async def _do_subscribe(self, channel_uuid: UUID):
        """Internal subscription helper."""
        try:
            await self.api.client.ws.subscribe("activity", channel_uuid)
            await self.api.client.ws.subscribe("chat_message", channel_uuid)
            await self.api.client.ws.subscribe("status", channel_uuid)
            self.log.debug(f"Subscribed to {channel_uuid}")
        except Exception as e:
            self.log.error(f"Failed to subscribe to {channel_uuid} in loop: {e}")

    async def stop(self):
        """Stop the WebSocket client."""
        self._running = False
        
        if self.api.client:
            try:
                await self.api.client.ws.close()
            except: pass
        self._subscriptions.clear()

    async def subscribe(self, channel_uuid: UUID):
        """Subscribe to events for a specific channel."""
        if not self.api.is_ready: return
        if channel_uuid in self._subscriptions: return

        self.log.info(f"Adding subscription to {channel_uuid}")
        self._subscriptions.add(channel_uuid)
        
        # We always call _do_subscribe; if not connected, the SDK will queue it or we'll retry on 'connect'
        await self._do_subscribe(channel_uuid)

    async def unsubscribe(self, channel_uuid: UUID):
        """Unsubscribe from events for a channel."""
        if not self.api.is_ready: return
        try:
            await self.api.client.ws.unsubscribe("activity", channel_uuid)
            await self.api.client.ws.unsubscribe("chat_message", channel_uuid)
            await self.api.client.ws.unsubscribe("status", channel_uuid)
            self._subscriptions.discard(channel_uuid)
        except Exception as e:
            self.log.error(f"Failed to unsubscribe from {channel_uuid}: {e}")

    async def _handle_status(self, event: Dict[str, Any]):
        """Handle stream status changes (online/offline)."""
        channel_id = event.get("channel_id")
        if not channel_id: return

        is_live = event.get("data", {}).get("is_live", False)
        self.log.info(f"WS Status Update: {channel_id} is now {'LIVE' if is_live else 'OFFLINE'}")
        
        await self.action_queue.put({
            "type": "ws_status",
            "channel_id": channel_id,
            "data": event.get("data", {})
        })

    async def _handle_activity(self, event: Dict[str, Any]):
        """Handle incoming activity events (follows, subs, etc.)."""
        channel_id = event.get("channel_id")
        if not channel_id: return

        await self.action_queue.put({
            "type": "activity", 
            "channel_id": channel_id,
            "data": event.get("data", {})
        })

    async def _handle_chat(self, event: Dict[str, Any]):
        """Handle incoming chat messages for synchronization."""
        channel_id = event.get("channel_id")
        if not channel_id: return
        
        await self.action_queue.put({
            "type": "chat_message",
            "channel_id": channel_id,
            "data": event.get("data", {})
        })
