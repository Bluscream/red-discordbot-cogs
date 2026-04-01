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
        self._last_identity: Dict[int, Dict[str, Any]] = {} # guild_id -> {nick, avatar_hash}
        self._last_webhook_profile: Dict[str, Dict[str, Any]] = {} # url -> {nick, avatar}
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
                                url = target.strip()
                                webhook = discord.Webhook.from_url(url, session=session)
                                
                                # Check if profile info is redundant
                                last_prof = self._last_webhook_profile.get(url, {})
                                use_nick = nick if nick != last_prof.get("nick") else None
                                use_avatar = avatar if avatar != last_prof.get("avatar") else None
                                
                                send_params = {"allowed_mentions": allowed}
                                if use_nick: send_params["username"] = use_nick
                                if use_avatar: send_params["avatar_url"] = use_avatar
                                
                                if isinstance(content, discord.Embed): send_params["embed"] = content
                                else: send_params["content"] = content
                                
                                await webhook.send(**send_params)
                                self._last_webhook_profile[url] = {"nick": nick, "avatar": avatar}
                            except discord.NotFound:
                                log.warning(f"Webhook deleted in Discord. Emitting prune request for: {target[:55]}...")
                                await self.put({"type": "prune_webhook", "payload": {"url": target}})
                            except Exception as e:
                                log.error(f"Webhook error: {e}")
                        else:
                            try:
                                # Guard against misconfigured channel targets
                                if not target or str(target).strip().lower() == "none":
                                    return
                                    
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
                            last_data = self.last_status_update.get(channel.id, {"time": 0, "text": None})
                            now = self.bot.loop.time()
                            
                            # Skip if text is identical to last successfully set status
                            if text == last_data.get("text"):
                                continue

                            if now - last_data["time"] >= 15: # 15s cooldown per channel status
                                try:
                                    await channel.edit(status=text)
                                    self.last_status_update[channel.id] = {"time": now, "text": text}
                                except Exception as e:
                                    log.warning(f"Status update failed for {channel.id}: {e}")

                    elif atype == "identity":
                        guild = payload.get("guild")
                        nick = payload.get("nick")
                        avatar = payload.get("avatar_bytes")
                        if guild and guild.me:
                            try:
                                # 1. Check current nickname without API call
                                current_nick = guild.me.nick or guild.me.display_name
                                nick_matches = (nick == current_nick) if nick is not None else True
                                
                                # 2. Check avatar hash cache
                                avatar_hash = hash(avatar) if avatar else None
                                last_hash = self._last_identity.get(guild.id, {}).get("avatar_hash")
                                avatar_matches = (avatar_hash == last_hash) if avatar is not None else True
                                
                                if nick_matches and avatar_matches:
                                    # log.debug(f"Skipping redundant identity update for guild {guild.id}")
                                    continue

                                params = {}
                                if not nick_matches: params["nick"] = nick[:32]
                                if not avatar_matches: params["avatar"] = avatar
                                
                                if params:
                                    await guild.me.edit(**params)
                                    self._last_identity[guild.id] = {"nick": nick, "avatar_hash": avatar_hash}
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
