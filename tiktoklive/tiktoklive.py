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
        import aiohttp
        # Disallow everyone/roles mentions for safety
        allowed = discord.AllowedMentions(everyone=False, roles=False, users=True)
        # Use bot's session if available (Red 3.5+) or create one
        session = getattr(self.bot, "session", None) or aiohttp.ClientSession()
        try:
            while True:
                try:
                    target, content, nick, avatar = await self.message_queue.get()
                    
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
                    
                    self.message_queue.task_done()
                    await asyncio.sleep(1.0) # Rate limit: 1 per second
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
            if v_chan and t_chan:
                await self._start_session(username, v_chan, t_chan)

    async def _start_session(self, username: str, voice_channel: int, text_channel: Union[int, str]):
        """Initializes both voice and chat monitoring for a user."""
        username = username.strip().replace("@", "")
        if username in self.active_sessions:
            return

        session = TikTokLiveSession(username, voice_channel, text_channel)
        self.active_sessions[username] = session
        
        # 1. Setup Chat Handler
        self.chat_handler.setup_client(session, self._stop_session)
        
        # 2. Setup Voice Handler
        voice_embed = await self.voice_handler.start_voice(session)
        if voice_embed:
            await self.message_queue.put((text_channel, voice_embed, None, None))

    async def _stop_session(self, session: TikTokLiveSession):
        """Stops both voice and chat components and cleans up resources."""
        if session.username not in self.active_sessions:
            return
            
        log.info(f"Stopping session for {session.username}")
        
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
        
        if isinstance(text_target, str):
            if not text_target.startswith("https://discord.com/api/webhooks/"):
                return await ctx.send(error("Invalid Webhook URL. Must start with `https://discord.com/api/webhooks/`"))
            target_val = text_target
            display_target = "Webhook"
        else:
            target_val = text_target.id
            display_target = text_target.mention

        async with self.config.monitored_users() as users:
            users[username] = {
                "voice_channel": voice_channel.id,
                "text_channel": target_val
            }
        
        await self._start_session(username, voice_channel.id, target_val)
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
