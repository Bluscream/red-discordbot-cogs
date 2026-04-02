import logging
import asyncio
from typing import Dict, Any, Callable, Optional
from uuid import UUID

class SynchraWSHandler:
    """Manages Synchra WebSocket connection and dispatches events to the cog."""
    
    def __init__(self, api_manager, action_queue):
        self.api = api_manager
        self.action_queue = action_queue
        self.log = logging.getLogger("red.blu.synchra.ws")
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the WebSocket client and register handlers."""
        if not self.api.is_ready:
            self.log.warning("API Manager not ready. WebSocket not started.")
            return

        self._running = True
        
        # Register handlers on the SDK's WS client
        @self.api.client.ws.on("activity")
        async def on_activity(event):
            await self._handle_activity(event)

        @self.api.client.ws.on("chat")
        async def on_chat(event):
            await self._handle_chat(event)

        # Connect
        await self.api.client.connect()
        self.log.info("Synchra WebSocket connection initiated.")

    async def stop(self):
        """Stop the WebSocket client."""
        self._running = False
        if self.api.client:
            await self.api.client.ws.close()

    async def subscribe(self, channel_uuid: UUID):
        """Subscribe to events for a specific channel."""
        if not self.api.is_ready: return
        self.log.info(f"Subscribing to WS events for channel: {channel_uuid}")
        await self.api.client.ws.subscribe("activity", channel_uuid)
        await self.api.client.ws.subscribe("chat", channel_uuid)

    async def unsubscribe(self, channel_uuid: UUID):
        """Unsubscribe from events for a channel."""
        if not self.api.is_ready: return
        await self.api.client.ws.unsubscribe("activity", channel_uuid)
        await self.api.client.ws.unsubscribe("chat", channel_uuid)

    async def _handle_activity(self, event: Dict[str, Any]):
        """Handle incoming activity events (follows, subs, etc.)."""
        # This can be used for Discord notifications
        data = event.get("data", {})
        self.log.debug(f"Received activity event: {data.get('type')}")
        # We can dispatch this to the action queue for processing in the cog
        await self.action_queue.put({"type": "ws_activity", "payload": event})

    async def _handle_chat(self, event: Dict[str, Any]):
        """Handle incoming chat messages for synchronization."""
        # Synchra chat events are unified across platforms
        data = event.get("data", {})
        if not data: return
        
        # Payload format based on SDK models/ws.py
        # We need to map this to our Discord bridge logic
        await self.action_queue.put({
            "type": "chat_message",
            "payload": {
                "platform": data.get("provider", "unknown"),
                "channel_id": data.get("provider_channel_id"), # Or map back to internal name
                "author": data.get("viewer_display_name") or data.get("viewer_name"),
                "message": data.get("message"), # This might need construction from parts if it's complex
                "raw_event": event
            }
        })
