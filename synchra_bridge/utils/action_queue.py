import asyncio
import discord
import aiohttp
import logging
from typing import Dict, Any, Optional, Callable, Union
from .retry import StaggeredRetry

log = logging.getLogger("red.blu.synchra_bridge.utils.action_queue")

class SynchraActionQueue:
    """
    Consolidated action queue for SynchraBridge.
    Handles rate-limited operations like webhooks, status updates, and Synchra broadcasts.
    """
    def __init__(self, bot: discord.Client, api_manager: Any, voice_handler: Any):
        self.bot = bot
        self.api = api_manager
        self.voice = voice_handler
        self.delay = 1.0 # Default delay between actions (seconds)
        self.queue = asyncio.Queue()
        self.last_status_update: Dict[int, float] = {}
        self._last_webhook_profile: Dict[str, Dict[str, Any]] = {} # url -> {nick, avatar}
        self._worker_task: Optional[asyncio.Task] = None
        self._custom_handlers: Dict[str, Callable] = {}

    def start(self):
        """Starts the background worker task."""
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker())
            log.info("Synchra ActionQueue worker started.")

    async def stop(self):
        """Stops the worker task and waits for the queue to drain."""
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
            log.info("Synchra ActionQueue worker stopped.")

    async def put(self, action: Dict[str, Any]):
        """Adds an action to the queue."""
        await self.queue.put(action)

    async def _worker(self):
        """Infinite loop to process actions from the queue."""
        async with aiohttp.ClientSession() as session:
            error_retry = StaggeredRetry(start=5.0, multiplier=2.0, max_val=60.0)
            while True:
                action = None
                try:
                    action = await self.queue.get()
                    atype = action.get("type", "unknown")
                    payload = action.get("payload", {})
                    
                    # log.debug(f"[ActionQueue] Executing {atype}")
                    
                    allowed = discord.AllowedMentions.none()

                    if atype == "webhook":
                        url = payload.get("url")
                        content = payload.get("content")
                        nick = payload.get("nick")
                        avatar = payload.get("avatar")
                        
                        if url:
                            try:
                                webhook = discord.Webhook.from_url(url, session=session)
                                
                                # Profile Caching
                                last_prof = self._last_webhook_profile.get(url, {})
                                use_nick = nick if nick != last_prof.get("nick") else None
                                use_avatar = avatar if avatar != last_prof.get("avatar") else None
                                
                                send_params = {"allowed_mentions": allowed}
                                if use_nick: send_params["username"] = use_nick[:80]
                                if use_avatar: send_params["avatar_url"] = use_avatar
                                
                                if isinstance(content, discord.Embed): send_params["embed"] = content
                                else: send_params["content"] = content
                                
                                await webhook.send(**send_params)
                                self._last_webhook_profile[url] = {"nick": nick, "avatar": avatar}
                            except discord.NotFound:
                                log.warning(f"Webhook deleted in Discord: {url[:50]}...")
                                # Signal for re-creation in the main cog if needed
                                # We can't easily signal back here without a callback or event
                            except Exception as e:
                                log.error(f"Webhook error: {e}")

                    elif atype == "message":
                        target_id = payload.get("target")
                        content = payload.get("content")
                        try:
                            channel = self.bot.get_channel(target_id)
                            if channel:
                                if isinstance(content, discord.Embed):
                                    await channel.send(embed=content, allowed_mentions=allowed)
                                else:
                                    await channel.send(content, allowed_mentions=allowed)
                        except Exception as e:
                            log.error(f"Channel send error: {e}")

                    elif atype == "synchra_chat":
                        channel_provider_id = payload.get("channel_provider_id")
                        message = payload.get("message")
                        user_provider_id = payload.get("user_provider_id")
                        if channel_provider_id and message and user_provider_id:
                            try:
                                await self.api.send_chat_message(channel_provider_id, message, user_provider_id)
                            except Exception as e:
                                log.error(f"Synchra broadcast error: {e}")

                    elif atype == "status":
                        channel_id = payload.get("channel_id")
                        text = payload.get("text")
                        
                        last_text = self.last_status_update.get(channel_id)
                        if text == last_text:
                            # Skip if status is exactly the same as last set
                            pass
                        else:
                            channel = self.bot.get_channel(channel_id)
                            if channel and hasattr(channel, "edit"):
                                try:
                                    await channel.edit(status=text)
                                    self.last_status_update[channel_id] = text
                                except Exception as e:
                                    log.warning(f"Failed to set VR status: {e}")

                    elif atype == "voice_connect":
                        session_obj = payload.get("session")
                        if session_obj:
                            await self.voice.start_voice(session_obj)

                    elif atype == "voice_disconnect":
                        session_obj = payload.get("session")
                        if session_obj:
                            await self.voice.stop_voice(session_obj)

                    elif atype == "callback":
                        func = payload.get("func")
                        if func:
                            try:
                                await func(*payload.get("args", []), **payload.get("kwargs", {}))
                            except Exception as e:
                                log.error(f"Callback error: {e}")

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    log.error(f"Worker iteration error: {e}")
                    await error_retry.sleep()
                finally:
                    if action is not None:
                        self.queue.task_done()
                        error_retry.reset() # Reset on successful (non-crashed) cycle
                    # Unified mandatory delay to prevent spamming any platform
                    await asyncio.sleep(self.delay)
