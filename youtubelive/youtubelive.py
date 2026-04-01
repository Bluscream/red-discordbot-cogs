import asyncio
import logging
import discord
import aiohttp
from typing import Dict, Optional, List, Union

from redbot.core import Config, commands, checks
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import success, error

from .session import YouTubeLiveSession
from .voice_handler import YouTubeVoiceHandler
from .chat_handler import YouTubeChatHandler
from .utils.action_queue import ActionQueue
from .utils.webhooks import delete_webhook_by_url, ensure_webhook

log = logging.getLogger("red.blu.youtubelive")

class YouTubeLive(commands.Cog):
    """Monitor YouTube Live streams and notify/voice bridge to Discord."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=928374562, force_registration=True)
        self.config.register_global(monitored_channels={})
        
        # Active sessions: {channel_id: YouTubeLiveSession}
        self.active_sessions: Dict[str, YouTubeLiveSession] = {}
        
        # Universal Action Queue
        self.action_queue = ActionQueue(self.bot)
        
        # Handlers
        self.chat_handler = YouTubeChatHandler(bot, self.action_queue)
        self.voice_handler = YouTubeVoiceHandler(bot, self.action_queue)
        
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
        """Starts monitoring for all configured channels on load."""
        channels = await self.config.monitored_channels()
        for channel_id, data in channels.items():
            await self._start_session(
                channel_id, 
                data["voice_channel"], 
                data["text_channel"],
                discord_channel_id=data.get("discord_channel_id")
            )
            if data.get("is_managed"):
                self.active_sessions[channel_id].is_managed = True

    async def _start_session(self, channel_id: str, voice_channel: int, text_channel: Any, discord_channel_id: Optional[int] = None):
        """Initializes a new monitoring session."""
        if channel_id in self.active_sessions:
            return
            
        session = YouTubeLiveSession(channel_id, voice_channel, text_channel, discord_channel_id=discord_channel_id)
        self.active_sessions[channel_id] = session
        
        # Start background polling
        session.monitor_task = self.bot.loop.create_task(self.chat_handler.monitor_loop(session))
        log.info(f"Initialized session for YouTube channel: {channel_id}")

    async def _stop_session(self, session: YouTubeLiveSession):
        """Stops an active session and cleans up resources."""
        log.info(f"Stopping session for YouTube: {session.channel_id}")
        
        # 1. Stop Monitoring
        if session.monitor_task:
            session.monitor_task.cancel()
            
        # 2. Disconnect Voice
        if session.voice_client:
            await self.voice_handler.stop_voice(session)
        
        # 3. Clean up Managed Webhook
        if session.is_managed and session.text_channel:
            await delete_webhook_by_url(
                session.text_channel, 
                reason=f"YouTube monitor for {session.channel_id} stopped."
            )

        if session.channel_id in self.active_sessions:
            del self.active_sessions[session.channel_id]

    @commands.group(name="youtube", aliases=["yt"])
    @checks.admin_or_permissions(manage_messages=True)
    async def youtube(self, ctx):
        """YouTube Live Bridge Commands."""
        pass

    @youtube.command(name="monitor")
    async def monitor(self, ctx, channel_id: str, 
                      voice_channel: Union[discord.VoiceChannel, discord.StageChannel], 
                      text_target: Union[discord.TextChannel, discord.VoiceChannel, discord.Thread, str]):
        """
        Start monitoring a YouTube channel by ID or @handle.
        text_target can be a Target Channel or a Webhook URL.
        """
        channel_id = channel_id.strip()
        
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
                webhook_url = await ensure_webhook(text_target, name=f"YouTube Mirror (@{channel_id})")
                if not webhook_url:
                    return await ctx.send(error("Failed to ensure webhook. Check permissions."))
                target_val = webhook_url
                display_target = f"Managed Webhook in {text_target.mention}"
                is_managed = True
                discord_channel_id = text_target.id
            except Exception as e:
                log.error(f"Webhook creation error: {e}")
                return await ctx.send(error("Failed to create webhook."))
        
        async with self.config.monitored_channels() as channels:
            channels[channel_id] = {
                "voice_channel": voice_channel.id,
                "text_channel": target_val,
                "discord_channel_id": discord_channel_id,
                "is_managed": is_managed
            }
        
        await self._start_session(channel_id, voice_channel.id, target_val, discord_channel_id=discord_channel_id)
        if is_managed:
            self.active_sessions[channel_id].is_managed = True
            
        await ctx.send(success(f"Monitoring **{channel_id}**. Voice: {voice_channel.mention} | Text: {display_target}"))

    @youtube.command(name="stop")
    async def stop(self, ctx, channel_id: str):
        """Stop monitoring a YouTube channel."""
        channel_id = channel_id.strip()
        if channel_id in self.active_sessions:
            await self._stop_session(self.active_sessions[channel_id])
            async with self.config.monitored_channels() as channels:
                if channel_id in channels:
                    del channels[channel_id]
            await ctx.send(success(f"Stopped monitoring **{channel_id}**."))
        else:
            await ctx.send(error(f"Not currently monitoring **{channel_id}**."))

    @youtube.command(name="list")
    async def list(self, ctx):
        """List all currently monitored YouTube channels."""
        channels = await self.config.monitored_channels()
        if not channels:
            return await ctx.send("No channels are currently being monitored.")
        
        msg = "**Monitored YouTube Channels:**\n"
        for cid, data in channels.items():
            status = "🔴 Live" if cid in self.active_sessions and self.active_sessions[cid].is_live else "⚫ Offline"
            msg += f"- **{cid}** ({status})\n"
        await ctx.send(msg)
