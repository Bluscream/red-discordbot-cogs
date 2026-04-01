import asyncio
import logging
import discord
import aiohttp
from typing import Dict, Optional, List, Union

from redbot.core import Config, commands, checks
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import success, error, warning, info

from .session import TwitchLiveSession
from .voice_handler import TwitchVoiceHandler
from .chat_handler import TwitchChatHandler
from .utils.action_queue import ActionQueue
from .utils.webhooks import delete_webhook_by_url, ensure_webhook

log = logging.getLogger("red.blu.twitchlive")

class TwitchLive(commands.Cog):
    """Monitor Twitch Live streams and notify/voice bridge to Discord."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=928374563, force_registration=True)
        self.config.register_global(
            client_id=None,
            client_secret=None,
            monitored_streamers={}
        )
        
        # Active sessions: {username: TwitchLiveSession}
        self.active_sessions: Dict[str, TwitchLiveSession] = {}
        
        # Universal Action Queue
        self.action_queue = ActionQueue(self.bot)
        
        # Handlers
        self.chat_handler = TwitchChatHandler(bot, self.action_queue, self.config)
        self.voice_handler = TwitchVoiceHandler(bot, self.action_queue)
        
        # Register Cog-Specific Handlers
        self.action_queue.register_handler("voice_connect", self._handle_voice_connect)
        self.action_queue.register_handler("voice_disconnect", self._handle_voice_disconnect)
        self.action_queue.start()
        
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
        """Starts monitoring for all configured streamers on load."""
        streamers = await self.config.monitored_streamers()
        for username, data in streamers.items():
            await self._start_session(
                username, 
                data["voice_channel"], 
                data["text_channel"],
                discord_channel_id=data.get("discord_channel_id")
            )
            if data.get("is_managed"):
                self.active_sessions[username].is_managed = True

    async def _start_session(self, username: str, voice_channel: int, text_channel: Any, discord_channel_id: Optional[int] = None):
        """Initializes a new monitoring session."""
        if username in self.active_sessions:
            return
            
        session = TwitchLiveSession(username, voice_channel, text_channel, discord_channel_id=discord_channel_id)
        self.active_sessions[username] = session
        
        # Start background polling
        session.monitor_task = self.bot.loop.create_task(self.chat_handler.monitor_loop(session))
        log.info(f"Initialized session for Twitch: {username}")

    async def _stop_session(self, session: TwitchLiveSession):
        """Stops an active session and cleans up resources."""
        log.info(f"Stopping session for Twitch: {session.username}")
        
        if session.monitor_task:
            session.monitor_task.cancel()
            
        if session.voice_client:
            await self.voice_handler.stop_voice(session)
        
        if session.is_managed and session.text_channel:
            await delete_webhook_by_url(
                session.text_channel, 
                reason=f"Twitch monitor for {session.username} stopped."
            )

        if session.username in self.active_sessions:
            del self.active_sessions[session.username]

    @commands.group(name="twitch", aliases=["tw"])
    @checks.admin_or_permissions(manage_messages=True)
    async def twitch(self, ctx):
        """Twitch Live Bridge Commands."""
        pass

    @twitch.group(name="set")
    @checks.is_owner()
    async def twitchset(self, ctx):
        """Configure Twitch API credentials."""
        pass

    @twitchset.command(name="credentials")
    async def set_creds(self, ctx, client_id: str, client_secret: str):
        """
        Set the Twitch Client ID and Client Secret for the Helix API.
        Get these from the Twitch Developer Console (https://dev.twitch.tv/).
        """
        await self.config.client_id.set(client_id)
        await self.config.client_secret.set(client_secret)
        try:
            await ctx.message.delete()
        except:
            pass
        await ctx.send(success("Twitch credentials updated. New monitor checks will use these."))

    @twitch.command(name="monitor")
    async def monitor(self, ctx, username: str, 
                      voice_channel: Union[discord.VoiceChannel, discord.StageChannel], 
                      text_target: Union[discord.TextChannel, discord.VoiceChannel, discord.Thread, str]):
        """
        Start monitoring a Twitch streamer by login name.
        text_target can be a Target Channel or a Webhook URL.
        """
        # API Check
        cid = await self.config.client_id()
        if not cid:
            return await ctx.send(warning(f"Twitch credentials are not set! Use `{ctx.prefix}twitch set credentials` first."))

        username = username.strip().replace("@", "").lower()
        
        target_val = text_target
        display_target = ""
        is_managed = False
        discord_channel_id = None
        
        if isinstance(text_target, str):
            if not text_target.startswith("https://discord.com/api/webhooks/"):
                return await ctx.send(error("Invalid Webhook URL."))
            target_val = text_target
            display_target = "Custom Webhook"
            discord_channel_id = ctx.channel.id
        elif isinstance(text_target, (discord.TextChannel, discord.VoiceChannel, discord.Thread)):
            # Managed Webhook
            try:
                webhook_url = await ensure_webhook(text_target, name=f"Twitch Mirror (@{username})")
                if not webhook_url:
                    return await ctx.send(error("Failed to ensure webhook. Check permissions."))
                target_val = webhook_url
                display_target = f"Managed Webhook in {text_target.mention}"
                is_managed = True
                discord_channel_id = text_target.id
            except Exception as e:
                log.error(f"Webhook creation error: {e}")
                return await ctx.send(error("Failed to create webhook."))
        
        async with self.config.monitored_streamers() as streamers:
            streamers[username] = {
                "voice_channel": voice_channel.id,
                "text_channel": target_val,
                "discord_channel_id": discord_channel_id,
                "is_managed": is_managed
            }
        
        await self._start_session(username, voice_channel.id, target_val, discord_channel_id=discord_channel_id)
        if is_managed:
            self.active_sessions[username].is_managed = True
            
        await ctx.send(success(f"Monitoring **{username}** on Twitch. Voice: {voice_channel.mention} | Text: {display_target}"))

    @twitch.command(name="stop")
    async def stop(self, ctx, username: str):
        """Stop monitoring a Twitch streamer."""
        username = username.strip().replace("@", "").lower()
        if username in self.active_sessions:
            await self._stop_session(self.active_sessions[username])
            async with self.config.monitored_streamers() as streamers:
                if username in streamers:
                    del streamers[username]
            await ctx.send(success(f"Stopped monitoring **{username}**."))
        else:
            await ctx.send(error(f"Not currently monitoring **{username}**."))

    @twitch.command(name="list")
    async def list(self, ctx):
        """List all currently monitored Twitch streamers."""
        streamers = await self.config.monitored_streamers()
        if not streamers:
            return await ctx.send("No streamers are currently being monitored.")
        
        msg = "**Monitored Twitch Streamers:**\n"
        for user, data in streamers.items():
            status = "🔴 Live" if user in self.active_sessions and self.active_sessions[user].is_live else "⚫ Offline"
            msg += f"- **{user}** ({status})\n"
        await ctx.send(msg)
