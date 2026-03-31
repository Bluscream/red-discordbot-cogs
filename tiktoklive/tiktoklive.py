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
        self.config = Config.get_conf(self, identifier=133769420)
        default_global = {
            "monitored_users": {}
        }
        self.config.register_global(**default_global)
        
        # Active sessions: {username: TikTokLiveSession}
        self.active_sessions: Dict[str, TikTokLiveSession] = {}
        
        # Rate-limited message queue: (channel_id, message_or_embed)
        self.message_queue = asyncio.Queue()
        
        # Handlers
        self.voice_handler = TikTokVoiceHandler(bot)
        self.chat_handler = TikTokChatHandler(bot, self.message_queue)
        
        # Worker tasks
        self.worker_task = None
        self.monitor_task = None

    async def cog_load(self):
        self.worker_task = self.bot.loop.create_task(self._message_worker())
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

    async def _message_worker(self):
        """Worker that processes the message queue at 1 message/sec."""
        log.info("TikTokLive message queue worker started.")
        while True:
            try:
                channel_id, content = await self.message_queue.get()
                channel = self.bot.get_channel(channel_id)
                if channel:
                    if isinstance(content, discord.Embed):
                        await channel.send(embed=content)
                    else:
                        await channel.send(content)
                self.message_queue.task_done()
                await asyncio.sleep(1.0) # Rate limit: 1 per second
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Worker error: {e}")
                await asyncio.sleep(5.0)

    async def _start_monitors(self):
        """Starts monitoring for all configured users on load."""
        await self.bot.wait_until_ready()
        users = await self.config.monitored_users()
        for username, data in users.items():
            await self._start_session(username, data['voice_channel_id'], data['text_channel_id'])

    async def _start_session(self, username: str, voice_channel_id: int, text_channel_id: int):
        """Initializes both voice and chat monitoring for a user."""
        username = username.strip().replace("@", "")
        if username in self.active_sessions:
            return

        session = TikTokLiveSession(username, voice_channel_id, text_channel_id)
        self.active_sessions[username] = session
        
        # 1. Setup Chat Handler
        self.chat_handler.setup_client(session, self._stop_session)
        
        # 2. Setup Voice Handler
        voice_embed = await self.voice_handler.start_voice(session)
        if voice_embed:
            await self.message_queue.put((text_channel_id, voice_embed))

    async def _stop_session(self, session: TikTokLiveSession):
        """Stops both voice and chat components and cleans up resources."""
        if session.username not in self.active_sessions:
            return
            
        log.info(f"Stopping session for {session.username}")
        
        # Stop components
        await self.chat_handler.stop_chat(session)
        await self.voice_handler.stop_voice(session)
        
        if session.username in self.active_sessions:
            del self.active_sessions[session.username]

    @commands.group()
    @checks.admin_or_permissions(manage_guild=True)
    async def tiktok(self, ctx):
        """TikTok Live Mirroring commands."""
        pass

    @tiktok.command()
    async def monitor(self, ctx, username: str, voice_channel: discord.VoiceChannel, text_channel: discord.TextChannel):
        """Start monitoring a TikTok user and mirror to specific channels."""
        username = username.strip().replace("@", "")
        
        async with self.config.monitored_users() as users:
            users[username] = {
                "voice_channel_id": voice_channel.id,
                "text_channel_id": text_channel.id
            }
        
        await self._start_session(username, voice_channel.id, text_channel.id)
        await ctx.send(success(f"Monitoring **@{username}**. Voice: {voice_channel.mention} | Text: {text_channel.mention}"))

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
            msg += f"- @{user}: {status}\n"
        await ctx.send(msg)
