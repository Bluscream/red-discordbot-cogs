import asyncio
import discord
import aiohttp
import logging
from typing import Dict, Any, Optional, Callable, Union

log = logging.getLogger("red.blu.stream_sync.utils.action_queue")

class ActionQueue:
    """
    Consolidated Discord action queue for all StreamSync platforms.
    Handles rate-limited operations like webhooks, status updates, and identity changes.
    """
    def __init__(self, bot: discord.Client):
        self.bot = bot
        self.queue = asyncio.Queue()
        self.last_status_update: Dict[int, float] = {}
        self._worker_task: Optional[asyncio.Task] = None
        self._custom_handlers: Dict[str, Callable] = {}

    def start(self):
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker())
            log.info("StreamSync ActionQueue worker started.")

    async def stop(self):
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
            log.info("StreamSync ActionQueue worker stopped.")

    def register_handler(self, action_type: str, handler: Callable):
        self._custom_handlers[action_type] = handler

    async def put(self, action: Dict[str, Any]):
        await self.queue.put(action)

    async def _worker(self):
        async with aiohttp.ClientSession() as session:
            while True:
                action = None
                try:
                    action = await self.queue.get()
                    atype = action.get("type")
                    payload = action.get("payload", {})
                    allowed = discord.AllowedMentions(everyone=False, roles=False, users=True)

                    if atype == "message":
                        target = payload.get("target")
                        content = payload.get("content")
                        nick = payload.get("nick")
                        avatar = payload.get("avatar")
                        
                        if isinstance(target, str) and target.strip().startswith("https://discord.com/api/webhooks/"):
                            try:
                                webhook = discord.Webhook.from_url(target.strip(), session=session)
                                if isinstance(content, discord.Embed):
                                    await webhook.send(embed=content, username=nick, avatar_url=avatar, allowed_mentions=allowed)
                                else:
                                    await webhook.send(content=content, username=nick, avatar_url=avatar, allowed_mentions=allowed)
                            except discord.NotFound:
                                log.error(f"Webhook URL is invalid or deleted: {target[:55]}...")
                            except Exception as e:
                                log.error(f"Webhook error: {e}")
                        else:
                            try:
                                chan_id = int(str(target).strip())
                                channel = self.bot.get_channel(chan_id)
                                if channel:
                                    if isinstance(content, discord.Embed):
                                        await channel.send(embed=content, allowed_mentions=allowed)
                                    else:
                                        await channel.send(content, allowed_mentions=allowed)
                            except Exception as e:
                                log.error(f"Channel send error: {e}")

                    elif atype == "status":
                        channel = payload.get("channel")
                        text = payload.get("text")
                        if channel and hasattr(channel, "edit"):
                            last_upd = self.last_status_update.get(channel.id, 0)
                            now = self.bot.loop.time()
                            if now - last_upd >= 15: # 15s cooldown per channel status
                                try:
                                    await channel.edit(status=text)
                                    self.last_status_update[channel.id] = now
                                except Exception as e:
                                    log.warning(f"Status update failed for {channel.id}: {e}")

                    elif atype == "identity":
                        guild = payload.get("guild")
                        nick = payload.get("nick")
                        avatar = payload.get("avatar_bytes")
                        if guild and guild.me:
                            try:
                                params = {}
                                if nick is not None: params["nick"] = nick[:32]
                                if avatar is not None: params["avatar"] = avatar
                                await guild.me.edit(**params)
                            except Exception as e:
                                log.warning(f"Identity update error: {e}")

                    elif atype == "callback":
                        func = payload.get("func")
                        if func:
                            try:
                                await func(*payload.get("args", []), **payload.get("kwargs", {}))
                            except Exception as e:
                                log.error(f"Callback error: {e}")

                    elif atype in self._custom_handlers:
                        try:
                            await self._custom_handlers[atype](payload)
                        except Exception as e:
                            log.error(f"Custom handler error ({atype}): {e}")

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    log.error(f"Worker iteration error: {e}")
                    await asyncio.sleep(5.0)
                finally:
                    if action is not None:
                        self.queue.task_done()
                    await asyncio.sleep(0.5)
