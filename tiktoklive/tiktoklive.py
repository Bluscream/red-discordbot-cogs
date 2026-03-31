import asyncio
import logging
import yt_dlp
from typing import Dict, Optional, List, Union

import discord
from redbot.core import Config, commands, checks
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import success, error, info, warning, bold
from TikTokLive import TikTokLiveClient
from TikTokLive.events import CommentEvent, ConnectEvent, DisconnectEvent, LiveEndEvent

log = logging.getLogger("red.blu.tiktoklive")

class TikTokLiveSession:
    def __init__(self, username: str, voice_channel_id: int, text_channel_id: Optional[int] = None):
        self.username = username
        self.voice_channel_id = voice_channel_id
        self.text_channel_id = text_channel_id
        
        self.client: Optional[TikTokLiveClient] = None
        self.voice_client: Optional[discord.VoiceClient] = None
        self.is_running = False
        self.hls_url: Optional[str] = None

class TikTokLive(commands.Cog):
    """
    Monitor TikTok lives and stream them to Discord voice channels.
    """

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=837461920, force_registration=True)
        
        default_global = {
            "streamers": {} # username -> {vc_id, text_id}
        }
        self.config.register_global(**default_global)
        
        self.active_sessions: Dict[str, TikTokLiveSession] = {}
        self._monitor_task: Optional[asyncio.Task] = None

    async def cog_load(self):
        self._monitor_task = self.bot.loop.create_task(self._status_monitor())
        log.info("TikTokLive monitoring task started.")

    def cog_unload(self):
        if self._monitor_task:
            self._monitor_task.cancel()
        for username in list(self.active_sessions.keys()):
            session = self.active_sessions.pop(username)
            self.bot.loop.create_task(self._stop_session(session))

    async def _stop_session(self, session: TikTokLiveSession):
        log.info(f"Stopping session for {session.username}")
        session.is_running = False
        if session.client:
            try:
                session.client.stop()
            except Exception as e:
                log.debug(f"Error stopping TikTokLiveClient for {session.username}: {e}")
        if session.voice_client and session.voice_client.is_connected():
            try:
                await session.voice_client.disconnect(force=True)
            except Exception as e:
                log.debug(f"Error disconnecting voice for {session.username}: {e}")

    async def _get_hls_url(self, username: str) -> Optional[str]:
        """Extract HLS URL using yt-dlp."""
        def _extract():
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'skip_download': True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                try:
                    url = f"https://www.tiktok.com/@{username}/live"
                    info_dict = ydl.extract_info(url, download=False)
                    if not info_dict:
                        return None
                    formats = info_dict.get('formats', [])
                    for f in formats:
                        if f.get('protocol') in ['m3u8_native', 'm3u8'] or f.get('ext') == 'm3u8':
                            return f.get('url')
                    if 'url' in info_dict and '.m3u8' in info_dict['url']:
                        return info_dict['url']
                except Exception as e:
                    log.error(f"Error extracting HLS for {username}: {e}")
            return None

        return await self.bot.loop.run_in_executor(None, _extract)

    async def _start_session(self, session: TikTokLiveSession):
        if session.is_running:
            return
        
        username = session.username
        vc_id = session.voice_channel_id
        vc = self.bot.get_channel(vc_id)
        
        if not vc or not isinstance(vc, discord.VoiceChannel):
            log.warning(f"Voice channel {vc_id} not found for {username}. Skipping.")
            return

        session.is_running = True
        log.info(f"TikTok streamer @{username} is LIVE. Connecting...")

        # 1. Join Voice
        guild = vc.guild
        if guild.voice_client:
            session.voice_client = guild.voice_client
            if guild.voice_client.channel.id != vc_id:
                await guild.voice_client.move_to(vc)
        else:
            try:
                session.voice_client = await vc.connect(timeout=20.0, reconnect=True)
            except Exception as e:
                log.error(f"Failed to connect to VC for {username}: {e}")
                session.is_running = False
                return

        # 2. Extract HLS and Start Playing
        hls_url = await self._get_hls_url(username)
        if hls_url:
            session.hls_url = hls_url
            try:
                audio_source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(
                    hls_url,
                    before_options="-re -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
                    options="-vn"
                ))
                session.voice_client.play(audio_source, after=lambda e: log.info(f"Stream ended for {username}: {e}"))
            except Exception as e:
                log.error(f"Failed to play audio for {username}: {e}")

        # 3. Post Announcement
        text_chan = self.bot.get_channel(session.text_channel_id or vc_id)
        if text_chan:
            embed = discord.Embed(
                title=f"🔴 @{username} is LIVE on TikTok!",
                url=f"https://www.tiktok.com/@{username}/live",
                color=discord.Color.red()
            )
            embed.set_footer(text="Streaming audio and mirroring chat into voice channel...")
            await text_chan.send(embed=embed)

        # 4. Setup Chat Client (Now Mandatory)
        self._setup_chat_client(session)

    def _setup_chat_client(self, session: TikTokLiveSession):
        client = TikTokLiveClient(unique_id=f"@{session.username}")
        session.client = client

        @client.on(CommentEvent)
        async def on_comment(event: CommentEvent):
            chan_id = session.text_channel_id or session.voice_channel_id
            channel = self.bot.get_channel(chan_id)
            if channel:
                # Check permissions
                if channel.permissions_for(channel.guild.me).send_messages:
                    try:
                        clean_msg = discord.utils.escape_mentions(event.comment)
                        await channel.send(f"💬 **{event.user.nickname}:** {clean_msg}")
                    except Exception as e:
                        log.debug(f"Mirror error for @{session.username}: {e}")

        @client.on(LiveEndEvent)
        async def on_live_end(event: LiveEndEvent):
            log.info(f"TikTok Live ended for @{session.username}")
            await self._stop_session(session)

        self.bot.loop.create_task(client.start())

    async def _status_monitor(self):
        """Main polling background task."""
        await self.bot.wait_until_ready()
        while True:
            try:
                streamers = await self.config.streamers()
                for username, data in streamers.items():
                    try:
                        if username not in self.active_sessions:
                            self.active_sessions[username] = TikTokLiveSession(
                                username=username,
                                voice_channel_id=data["vc_id"],
                                text_channel_id=data.get("text_id")
                            )
                        
                        session = self.active_sessions[username]
                        
                        temp_client = TikTokLiveClient(unique_id=f"@{username}")
                        is_live = await temp_client.is_live()
                        
                        if is_live and not session.is_running:
                            await self._start_session(session)
                        elif not is_live and session.is_running:
                            await self._stop_session(session)
                            
                    except Exception as e:
                        log.error(f"Status check failed for @{username}: {e}")
                        
                await asyncio.sleep(120) 
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Fatal error in status monitor: {e}")
                await asyncio.sleep(60)

    @commands.group(name="tiktok")
    @checks.admin_or_permissions(manage_guild=True)
    async def _tiktok(self, ctx: commands.Context):
        """TikTokLive monitoring commands."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help()

    @_tiktok.command(name="monitor")
    async def _monitor(self, ctx: commands.Context, username: str, voice_channel: discord.VoiceChannel):
        """Add a TikTok streamer to monitor."""
        username = username.lstrip("@").strip().lower()
        async with self.config.streamers() as streamers:
            streamers[username] = {
                "vc_id": voice_channel.id,
                "text_id": voice_channel.id
            }
        
        await ctx.send(success(f"Now monitoring **@{username}**. I will join {voice_channel.mention} and mirror chat when they go live."))
        if username in self.active_sessions:
            del self.active_sessions[username]

    @_tiktok.command(name="stop")
    async def _stop_cmd(self, ctx: commands.Context, username: str):
        """Stop monitoring a TikTok streamer."""
        username = username.lstrip("@").strip().lower()
        async with self.config.streamers() as streamers:
            if username in streamers:
                del streamers[username]
                if username in self.active_sessions:
                    await self._stop_session(self.active_sessions[username])
                    del self.active_sessions[username]
                await ctx.send(success(f"Stopped monitoring **@{username}**."))
            else:
                await ctx.send(error(f"I am not monitoring **@{username}**."))

    @_tiktok.command(name="list")
    async def _list(self, ctx: commands.Context):
        """List monitored TikTok streamers."""
        streamers = await self.config.streamers()
        if not streamers:
            return await ctx.send("No streamers are being monitored.")
        
        msg = "**Monitored TikTok Streamers:**\n"
        for username, data in streamers.items():
            vc = self.bot.get_channel(data['vc_id'])
            vc_name = vc.name if vc else "Unknown VC"
            status = "🔴 Live" if username in self.active_sessions and self.active_sessions[username].is_running else "⚪ Offline"
            msg += f"- @{username}: {vc_name} ({status})\n"
        
        await ctx.send(msg)

    @_tiktok.command(name="check")
    async def _check_now(self, ctx: commands.Context):
        """Trigger a status check now."""
        await ctx.send("Checking statuses...")
        self.bot.loop.create_task(self._status_monitor_once())
        await ctx.send(success("Background check triggered."))

    async def _status_monitor_once(self):
        streamers = await self.config.streamers()
        for username, data in streamers.items():
            if username not in self.active_sessions:
                self.active_sessions[username] = TikTokLiveSession(
                    username=username,
                    voice_channel_id=data["vc_id"],
                    text_channel_id=data.get("text_id")
                )
            session = self.active_sessions[username]
            try:
                is_live = await TikTokLiveClient(unique_id=f"@{username}").is_live()
                if is_live and not session.is_running:
                    await self._start_session(session)
                elif not is_live and session.is_running:
                    await self._stop_session(session)
            except:
                pass
