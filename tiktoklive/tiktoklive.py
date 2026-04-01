import asyncio
import logging
import discord
from typing import Dict, Optional, List, Union

from redbot.core import Config, commands, checks
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import success, error, info, bold

from .session import TikTokLiveSession
from .voice_handler import TikTokVoiceHandler
from .chat_handler import TikTokChatHandler

log = logging.getLogger("red.blu.tiktoklive")

class TikTokLive(commands.Cog):
    """Monitor TikTok Live streams and mirror chat to Discord."""
    
    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=943123456)
        default_global = {
            "monitored_users": {},
            "session_id": None,
            "tt_target_idc": None
        }
        self.config.register_global(**default_global)
        
        # Active sessions: {username: TikTokLiveSession}
        self.active_sessions: Dict[str, TikTokLiveSession] = {}
        
        # Universal Action Queue: (ActionDict)
        self.action_queue = asyncio.Queue()
        
        # Throttling state: {channel_id: last_update_timestamp}
        self.last_status_update: Dict[int, float] = {}
        
        # Handlers
        self.voice_handler = TikTokVoiceHandler(bot, self.action_queue)
        self.chat_handler = TikTokChatHandler(bot, self.action_queue)
        
        # Worker tasks
        self.worker_task = None
        self.monitor_task = None

    async def cog_load(self):
        self.worker_task = self.bot.loop.create_task(self._action_worker())
        self.monitor_task = self.bot.loop.create_task(self._start_monitors())

    async def cog_unload(self):
        if self.worker_task:
            self.worker_task.cancel()
        if self.monitor_task:
            self.monitor_task.cancel()
        
        # Explicit clean-up of all active sessions
        usernames = list(self.active_sessions.keys())
        for username in usernames:
            await self._stop_session(self.active_sessions[username])

    async def _action_worker(self):
        """Universal Action Worker. Handles messages, status updates, and identity changes."""
        log.info("TikTokLive action queue worker started.")
        import aiohttp
        # Disallow everyone/roles mentions for safety
        allowed = discord.AllowedMentions(everyone=False, roles=False, users=True)
        # Use bot's session if available (Red 3.5+) or create one
        session = getattr(self.bot, "session", None) or aiohttp.ClientSession()
        try:
            while True:
                try:
                    action = await self.action_queue.get()
                    atype = action.get("type", "message")
                    payload = action.get("payload", {})
                    
                    if atype == "message":
                        # Payload: target, content, nick, avatar
                        target = payload.get("target")
                        content = payload.get("content")
                        nick = payload.get("nick")
                        avatar = payload.get("avatar")
                        
                        if isinstance(target, str) and target.strip().startswith("https://discord.com/api/webhooks/"):
                            # Webhook Mode
                            url = target.strip()
                            try:
                                webhook = discord.Webhook.from_url(url, session=session)
                                if isinstance(content, discord.Embed):
                                    await webhook.send(embed=content, username=nick, avatar_url=avatar, allowed_mentions=allowed)
                                else:
                                    await webhook.send(content=content, username=nick, avatar_url=avatar, allowed_mentions=allowed)
                            except discord.NotFound:
                                log.error(f"Webhook 404: The webhook URL seems invalid or was deleted. URL start: {url[:55]}...")
                            except discord.HTTPException as e:
                                log.error(f"Webhook HTTP error: {e.status} {e.text} (Code: {e.code})")
                            except Exception as e:
                                log.error(f"Webhook unexpected error: {e}")
                        else:
                            # Standard Channel Mode
                            try:
                                chan_id = int(str(target).strip())
                                channel = self.bot.get_channel(chan_id)
                                if channel:
                                    if isinstance(content, discord.Embed):
                                        await channel.send(embed=content, allowed_mentions=allowed)
                                    else:
                                        await channel.send(content, allowed_mentions=allowed)
                                else:
                                    log.warning(f"Could not find channel {chan_id}")
                            except ValueError:
                                log.error(f"Invalid channel target: {target}")

                    elif atype == "status":
                        # Payload: channel, text
                        channel = payload.get("channel")
                        text = payload.get("text")
                        if channel and hasattr(channel, "edit"):
                            # Throttling: 15 seconds per channel
                            last_upd = self.last_status_update.get(channel.id, 0)
                            now = self.bot.loop.time()
                            if now - last_upd < 15:
                                # Skip too frequent updates (but always allow 'Offline'?)
                                # Actually, keep it simple for now and skip.
                                pass
                            else:
                                try:
                                    await channel.edit(status=text)
                                    self.last_status_update[channel.id] = now
                                    log.info(f"Updated VC status for {channel.id}: {text}")
                                except Exception as e:
                                    log.warning(f"Failed to set VC status: {e}")

                    elif atype == "identity":
                        # Payload: guild, nick, avatar_bytes
                        guild = payload.get("guild")
                        nick = payload.get("nick")
                        avatar = payload.get("avatar_bytes")
                        if guild and guild.me:
                            try:
                                params = {}
                                if nick is not None: params["nick"] = nick[:32]
                                if avatar is not None: params["avatar"] = avatar
                                await guild.me.edit(**params)
                                log.info(f"Updated bot identity in {guild.name}")
                            except Exception as e:
                                log.warning(f"Failed to update identity: {e}")

                    elif atype == "callback":
                        # Payload: func, args, kwargs
                        func = payload.get("func")
                        args = payload.get("args", [])
                        kwargs = payload.get("kwargs", {})
                        if func:
                            try:
                                await func(*args, **kwargs)
                            except Exception as e:
                                log.error(f"Callback execution error: {e}")
                    
                    self.action_queue.task_done()
                    await asyncio.sleep(0.5) # Rate limit: 0.5s delay between any actions
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    log.error(f"Worker iteration error: {e}")
                    await asyncio.sleep(5.0)
        finally:
            if not hasattr(self.bot, "session") and isinstance(session, aiohttp.ClientSession):
                await session.close()

    async def _start_monitors(self):
        """Starts monitoring for all configured users on load."""
        await self.bot.wait_until_ready()
        users = await self.config.monitored_users()
        log.info(f"Starting monitors for {len(users)} users.")
        for username, data in users.items():
            # Migration logic for old keys
            v_chan = data.get('voice_channel') or data.get('voice_channel_id')
            t_chan = data.get('text_channel') or data.get('text_channel_id')
            d_chan = data.get('discord_channel_id') or (t_chan if isinstance(t_chan, int) else None)
            if v_chan and t_chan:
                await self._start_session(username, v_chan, t_chan, discord_channel_id=d_chan)

    async def _start_session(self, username: str, voice_channel: int, text_channel: Union[int, str], discord_channel_id: Optional[int] = None):
        """Initializes both voice and chat monitoring for a user."""
        username = username.strip().replace("@", "")
        if username in self.active_sessions:
            return

        session_id = await self.config.session_id()
        tt_target_idc = await self.config.tt_target_idc()
        session = TikTokLiveSession(username, voice_channel, text_channel, discord_channel_id=discord_channel_id)
        self.active_sessions[username] = session
        
        # 1. Setup Chat Handler
        self.chat_handler.setup_client(session, self._stop_session, session_id=session_id, tt_target_idc=tt_target_idc)
        
        # 2. Setup Voice Handler
        voice_embed = await self.voice_handler.start_voice(session)
        if voice_embed:
            await self.action_queue.put({
                "type": "message",
                "payload": {"target": text_channel, "content": voice_embed}
            })

    async def _stop_session(self, session: TikTokLiveSession):
        """Stops both voice and chat components and cleans up resources."""
        if session.username not in self.active_sessions:
            return
            
        log.info(f"Stopping session for {session.username}")
        
        # 3. Clean up Managed Webhook
        if session.is_managed and session.text_channel:
            try:
                # text_channel stores the webhook URL in managed mode
                webhook = discord.Webhook.from_url(session.text_channel, session=getattr(self.bot, "session", None))
                await webhook.delete(reason=f"TikTok monitor for @{session.username} stopped.")
                log.info(f"Deleted managed webhook for @{session.username}")
            except Exception as e:
                log.error(f"Failed to delete managed webhook for @{session.username}: {e}")

        if session.username in self.active_sessions:
            del self.active_sessions[session.username]

    @commands.group()
    @checks.is_owner()
    async def tiktokset(self, ctx):
        """Configure global TikTok settings."""
        pass

    @tiktokset.command(name="session")
    async def set_session(self, ctx, session_id: str, tt_target_idc: str):
        """
        Set the TikTok sessionid and tt_target_idc cookies for chat bridging.
        Get these from your browser's cookies (tt.com) while logged in.
        """
        await self.config.session_id.set(session_id)
        await self.config.tt_target_idc.set(tt_target_idc)
        await ctx.message.delete()
        await ctx.send(success(f"TikTok session updated (IDC: `{tt_target_idc}`). New sessions will use this for bridging."))

    @commands.group()
    @checks.admin_or_permissions(manage_guild=True)
    async def tiktok(self, ctx):
        """TikTok Live Mirroring commands."""
        pass

    @tiktok.command()
    async def monitor(self, ctx, username: str, 
                      voice_channel: Union[discord.VoiceChannel, discord.StageChannel], 
                      text_target: Union[discord.TextChannel, discord.VoiceChannel, discord.Thread, str]):
        """
        Start monitoring a TikTok user.
        text_target can be a Channel ID or a Discord Webhook URL.
        """
        username = username.strip().replace("@", "")
        
        target_val = text_target
        display_target = ""
        is_managed = False
        discord_channel_id = None
        
        if isinstance(text_target, str):
            if not text_target.startswith("https://discord.com/api/webhooks/"):
                return await ctx.send(error("Invalid Webhook URL. Must start with `https://discord.com/api/webhooks/`"))
            target_val = text_target
            display_target = "Custom Webhook"
            discord_channel_id = ctx.channel.id # Assume current channel for bridge
        elif isinstance(text_target, (discord.TextChannel, discord.VoiceChannel, discord.Thread)):
            # Automated Webhook Creation
            try:
                # Check permissions
                if not text_target.permissions_for(ctx.me).manage_webhooks:
                    return await ctx.send(error(f"I need `Manage Webhooks` permission in {text_target.mention}!"))
                
                avatar_bytes = await self.bot.user.display_avatar.read()
                webhook = await text_target.create_webhook(
                    name=f"@{username}",
                    avatar=avatar_bytes,
                    reason=f"Automated TikTok monitor setup by {ctx.author}"
                )
                target_val = webhook.url
                display_target = f"Managed Webhook in {text_target.mention}"
                is_managed = True
                discord_channel_id = text_target.id
            except discord.HTTPException as e:
                log.error(f"Failed to create webhook: {e}")
                return await ctx.send(error(f"Failed to create webhook: {e.text}"))
        else:
            target_val = text_target.id
            display_target = text_target.mention
            discord_channel_id = text_target.id

        async with self.config.monitored_users() as users:
            users[username] = {
                "voice_channel": voice_channel.id,
                "text_channel": target_val,
                "discord_channel_id": discord_channel_id,
                "is_managed": is_managed
            }
        
        await self._start_session(username, voice_channel.id, target_val, discord_channel_id=discord_channel_id)
        if is_managed:
            # Mark the runtime session as managed too
            self.active_sessions[username].is_managed = True
        
        await ctx.send(success(f"Monitoring **@{username}**. Voice: {voice_channel.mention} | Text: {display_target}"))

    @tiktok.command()
    async def stop(self, ctx, username: str):
        """Stop monitoring a TikTok user."""
        username = username.strip().replace("@", "")
        if username in self.active_sessions:
            await self._stop_session(self.active_sessions[username])
            async with self.config.monitored_users() as users:
                if username in users:
                    del users[username]
            await ctx.send(success(f"Stopped monitoring **@{username}**."))
        else:
            await ctx.send(error(f"Not currently monitoring **@{username}**."))

    @tiktok.command()
    async def list(self, ctx):
        """List all currently monitored TikTok users."""
        users = await self.config.monitored_users()
        if not users:
            return await ctx.send(info("No users are currently being monitored."))
        
        msg = "**Monitored TikTok Users:**\n"
        for user, data in users.items():
            status = "🟢 Active" if user in self.active_sessions else "🔴 Idle"
            target = data.get('text_channel') or data.get('text_channel_id')
            target_str = "Webhook" if isinstance(target, str) else f"<#{target}>"
            msg += f"- @{user}: {status} (Target: {target_str})\n"
        await ctx.send(msg)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Bridge Discord messages to TikTok if authenticated."""
        # 1. Broad filters: No bots, webhooks, or empty messages
        if message.author.bot or message.webhook_id or not message.guild:
            return
        
        # 2. Command/Self filter
        content = message.clean_content.strip()
        if not content or content.startswith("!"):
            return
        
        # 3. Rich content filter: No embeds
        if message.embeds:
            return

        # Check if message is in a monitored channel target
        for username, session in self.active_sessions.items():
            if session.discord_channel_id == message.channel.id:
                # Found a matching session!
                # We also need a session_id set globally to bridge
                session_id = await self.config.session_id()
                if not session_id:
                    continue # Silent fallback: No authenticated account
                
                # Format: "DiscordUser: Message"
                # TikTok has a short limit, we'll try to keep it compact
                author_name = message.author.display_name[:12]
                bridge_text = f"{author_name}: {content}"
                
                # Push bridging message to action queue
                await self.action_queue.put({
                    "type": "message",
                    "payload": {
                        "target": session.text_channel,
                        "content": bridge_text,
                        "nick": f"{author_name} (@{message.author.name})",
                        "avatar": str(message.author.display_avatar.url)
                    }
                })
                # No longer direct call: await self.chat_handler.send_room_chat(session, bridge_text)
                # Correct: Bridge Discord->TikTok still direct call (TikTok rate limit is high/separate)
                await self.chat_handler.send_room_chat(session, bridge_text)
