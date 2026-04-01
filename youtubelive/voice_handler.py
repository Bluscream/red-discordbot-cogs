import asyncio
from typing import Optional
import logging
import yt_dlp
import discord
import aiohttp
from redbot.core.bot import Red
from .session import YouTubeLiveSession
from .utils.action_queue import ActionQueue

log = logging.getLogger("red.blu.youtubelive.voice")

class YouTubeVoiceHandler:
    def __init__(self, bot: Red, action_queue: ActionQueue):
        self.bot = bot
        self.action_queue = action_queue

    async def _get_hls_url(self, channel_id: str) -> Optional[str]:
        """Extract HLS stream URL using yt-dlp."""
        ydl_opts = {
            'format': 'best',
            'quiet': True,
            'no_warnings': True,
        }
        # Try handle, channel link, etc.
        url = f"https://www.youtube.com/channel/{channel_id}/live"
        if channel_id.startswith("@"):
            url = f"https://www.youtube.com/{channel_id}/live"
            
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await asyncio.to_thread(ydl.extract_info, url, download=False)
                return info.get('url')
        except Exception as e:
            log.error(f"yt-dlp failed to extract HLS for {channel_id}: {e}")
            return None

    async def start_voice(self, session: YouTubeLiveSession):
        """Connects to the voice channel and starts playing the YouTube stream."""
        voice_channel = self.bot.get_channel(session.voice_channel)
        if not voice_channel:
            log.error(f"Voice channel {session.voice_channel} not found.")
            return

        current_vc = session.voice_client or voice_channel.guild.voice_client
        
        if current_vc and current_vc.is_connected():
            session.voice_client = current_vc
            if current_vc.channel.id != voice_channel.id:
                try:
                    await current_vc.move_to(voice_channel)
                except Exception as e:
                    log.error(f"Failed to move to VC for {session.channel_id}: {e}")
        else:
            try:
                session.voice_client = await voice_channel.connect(timeout=20.0, reconnect=True)
            except Exception as e:
                log.error(f"Failed to connect to VC for {session.channel_id}: {e}")
                return

        if session.voice_client and session.voice_client.is_connected():
            hls_url = await self._get_hls_url(session.channel_id)
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
                        
                    session.voice_client.play(
                        audio_source, 
                        after=lambda e: log.info(f"Stream ended for {session.channel_id}: {e}")
                    )
                    log.info(f"Started playback for {session.channel_id} in {voice_channel.name}")
                    
                    # Update Voice Channel Status via queue
                    await self.action_queue.put({
                        "type": "status",
                        "payload": {"channel": voice_channel, "text": "🔴 YouTube Live"}
                    })

                    embed = discord.Embed(
                        description=f"🔊 Started streaming **{session.channel_id}**'s live audio.",
                        color=discord.Color.red()
                    )
                    return embed
                except Exception as e:
                    log.error(f"FFmpeg play error for {session.channel_id}: {e}")
        return None

    async def stop_voice(self, session: YouTubeLiveSession):
        """Disconnects and cleans up voice resources."""
        if session.voice_client:
            try:
                if session.voice_client.is_playing():
                    session.voice_client.stop()
                
                await self.action_queue.put({
                    "type": "status",
                    "payload": {"channel": session.voice_client.channel, "text": "⚫ Offline"}
                })
                await session.voice_client.disconnect(force=True)
            except Exception as e:
                log.error(f"Error disconnecting voice for {session.channel_id}: {e}")
            session.voice_client = None
