import asyncio
import logging
import discord
import aiohttp
from typing import Dict, Optional, List, Union

from redbot.core import Config, commands, checks
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import success, error

from .session import TikTokLiveSession
from .voice_handler import TikTokVoiceHandler
from .chat_handler import TikTokChatHandler
from .utils.action_queue import ActionQueue
from .utils.webhooks import delete_webhook_by_url, ensure_webhook

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
        
        # Universal Action Queue
        self.action_queue = ActionQueue(self.bot)
        
        # Handlers
        self.chat_handler = TikTokChatHandler(bot, self.action_queue)
        self.voice_handler = TikTokVoiceHandler(bot, self.action_queue)
        
        # Register Cog-Specific Handlers
        self.action_queue.register_handler("voice_connect", self._handle_voice_connect)
        self.action_queue.register_handler("voice_disconnect", self._handle_voice_disconnect)
        self.action_queue.start()
        
        # Worker tasks
        self.monitor_task = None

    async def cog_load(self):
        self.monitor_task = self.bot.loop.create_task(self._start_monitors())

    def cog_unload(self):
        """Cleanup sessions and tasks on unload."""
        if self.monitor_task:
            self.monitor_task.cancel()
        
        self.bot.loop.create_task(self.action_queue.stop())
        
        for session in list(self.active_sessions.values()):
            self.bot.loop.create_task(self._stop_session(session))

    async def _handle_voice_connect(self, payload: dict):
        session = payload.get("session")
        if session and not session.voice_client:
            voice_embed = await self.voice_handler.start_voice(session)
            if voice_embed and session.text_channel:
                await self.action_queue.put({
                    "type": "message",
                    "payload": {"target": session.text_channel, "content": voice_embed}
                })

    async def _handle_voice_disconnect(self, payload: dict):
        session = payload.get("session")
        if session:
            await self.voice_handler.stop_voice(session)

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
        
        # 2. Voice auto-join moves to ConnectEvent triggering "voice_connect"

    async def _stop_session(self, session: TikTokLiveSession):
        """Stops both voice and chat components and cleans up resources."""
        if session.username not in self.active_sessions:
            return
            
        log.info(f"Stopping session for {session.username}")
        
        # 1. Stop TikTok Web Client
        await self.chat_handler.stop_chat(session)
        
        # 2. Stop Voice Connection
        await self.voice_handler.stop_voice(session)
        
        # 3. Clean up Managed Webhook
        if session.is_managed and session.text_channel:
            await delete_webhook_by_url(
                session.text_channel, 
                reason=f"TikTok monitor for @{session.username} stopped."
            )

        if session.username in self.active_sessions:
            del self.active_sessions[session.username]

    @commands.group(aliases=["tt"])
    @checks.admin_or_permissions(manage_guild=True)
    async def tiktok(self, ctx):
        """TikTok Live Mirroring commands."""
        pass

    @tiktok.group(name="set")
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
        try:
            await ctx.message.delete()
        except:
            pass
        await ctx.send(success(f"TikTok session updated (IDC: `{tt_target_idc}`). New sessions will use this for bridging."))

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
                webhook_url = await ensure_webhook(text_target, name=f"@{username}")
                if not webhook_url:
                    return await ctx.send(error(f"Failed to ensure webhook in {text_target.mention}. Check permissions."))
                
                target_val = webhook_url
                display_target = f"Managed Webhook in {text_target.mention}"
                is_managed = True
                discord_channel_id = text_target.id
            except Exception as e:
                log.error(f"Failed to create webhook: {e}")
                return await ctx.send(error("Failed to create webhook."))
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
