import asyncio
from typing import Optional, Dict, Any
import logging
import yt_dlp
import discord
import aiohttp
from redbot.core.bot import Red
from .session import StreamSession
from .utils.action_queue import ActionQueue

log = logging.getLogger("red.blu.stream_sync.voice")

class UnifiedVoiceHandler:
    def __init__(self, bot: Red, action_queue: ActionQueue):
        self.bot = bot
        self.action_queue = action_queue

    async def _extract_hls_url(self, platform: str, channel_id: str) -> Optional[str]:
        """Generic HLS extraction using yt-dlp."""
        url = ""
        if platform == "tiktok":
            # TikTok logic is handled separately in its platform module usually, 
            # but we can try generic here if needed.
            url = f"https://www.tiktok.com/@{channel_id}/live"
        elif platform == "twitch":
            url = f"https://www.twitch.tv/{channel_id}"
        elif platform == "youtube":
            url = f"https://www.youtube.com/@{channel_id}/live" if channel_id.startswith("@") else f"https://www.youtube.com/channel/{channel_id}/live"

        ydl_opts = {'format': 'best', 'quiet': True, 'no_warnings': True}
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await asyncio.to_thread(ydl.extract_info, url, download=False)
                return info.get('url')
        except Exception as e:
            log.error(f"yt-dlp extraction failed for {platform}/{channel_id}: {e}")
            return None

    async def _handle_identity(self, session: StreamSession, guild: discord.Guild, set_identity: bool = True):
        """Standardized bot identity synchronization for all platforms."""
        me = guild.me
        if set_identity:
            session.original_nick = me.nick
            new_nick = f"@{session.channel_id}"[:32]
            await self.action_queue.put({
                "type": "identity",
                "payload": {"guild": guild, "nick": new_nick}
            })
            
            if session.avatar_url:
                async def _sync_avatar():
                    try:
                        async with aiohttp.ClientSession() as cs:
                            async with cs.get(session.avatar_url) as r:
                                if r.status == 200:
                                    img_bytes = await r.read()
                                    await self.action_queue.put({
                                        "type": "identity",
                                        "payload": {"guild": guild, "avatar_bytes": img_bytes}
                                    })
                    except: pass
                await self.action_queue.put({"type": "callback", "payload": {"func": _sync_avatar}})
        else:
            # Revert
            await self.action_queue.put({
                "type": "identity",
                "payload": {"guild": guild, "nick": session.original_nick, "avatar_bytes": None}
            })

    async def start_voice(self, session: StreamSession):
        """The core voice bridge for StreamSync."""
        voice_channel = self.bot.get_channel(session.voice_channel)
        if not voice_channel:
            return
            
        current_vc = session.voice_client or voice_channel.guild.voice_client
        if current_vc and current_vc.is_connected():
            session.voice_client = current_vc
            if current_vc.channel.id != voice_channel.id:
                await current_vc.move_to(voice_channel)
        else:
            try:
                session.voice_client = await voice_channel.connect(timeout=20.0, reconnect=True)
            except Exception as e:
                log.error(f"VC connection failed for {session.channel_id}: {e}")
                return

        if session.voice_client and session.voice_client.is_connected():
            hls_url = await self._extract_hls_url(session.platform, session.channel_id)
            if hls_url:
                session.hls_url = hls_url
                try:
                    audio_source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(
                        hls_url,
                        before_options="-re -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
                        options="-vn"
                    ))
                    if session.voice_client.is_playing():
                        session.voice_client.stop()
                    
                    session.voice_client.play(audio_source)
                    
                    # Sync Identity & Status
                    await self._handle_identity(session, voice_channel.guild, set_identity=True)
                    await self.action_queue.put({
                        "type": "status",
                        "payload": {"channel": voice_channel, "text": f"🔴 {session.platform.capitalize()} Live"}
                    })
                    
                    return discord.Embed(
                        description=f"🔊 Streaming **{session.channel_id}** from {session.platform.capitalize()}.",
                        color=discord.Color.green()
                    )
                except Exception as e:
                    log.error(f"FFmpeg error: {e}")
        return None

    async def stop_voice(self, session: StreamSession):
        if session.voice_client:
            try:
                if session.voice_client.is_playing():
                    session.voice_client.stop()
                
                await self._handle_identity(session, session.voice_client.guild, set_identity=False)
                await self.action_queue.put({
                    "type": "status",
                    "payload": {"channel": session.voice_client.channel, "text": "⚫ Offline"}
                })
                await session.voice_client.disconnect(force=True)
            except Exception as e:
                log.error(f"VC disconnect error: {e}")
            session.voice_client = None
