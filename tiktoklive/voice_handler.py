import asyncio
import logging
import yt_dlp
import discord
from redbot.core.utils.chat_formatting import error
from .session import TikTokLiveSession

log = logging.getLogger("red.blu.tiktoklive.voice")

class TikTokVoiceHandler:
    def __init__(self, bot):
        self.bot = bot

    async def _get_hls_url(self, username: str) -> Optional[str]:
        """Extract HLS stream URL using yt-dlp."""
        ydl_opts = {
            'format': 'best',
            'quiet': True,
            'no_warnings': True,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await asyncio.to_thread(ydl.extract_info, f"https://www.tiktok.com/@{username}/live", download=False)
                return info.get('url')
        except Exception as e:
            log.error(f"yt-dlp failed to extract HLS for {username}: {e}")
            return None

    async def start_voice(self, session: TikTokLiveSession):
        """Connects to the voice channel and starts playing the TikTok stream."""
        voice_channel = self.bot.get_channel(session.voice_channel_id)
        if not voice_channel:
            log.error(f"Voice channel {session.voice_channel_id} not found.")
            return

        # 1. Connect or Move
        if session.voice_client and session.voice_client.is_connected():
            if session.voice_client.channel.id != voice_channel.id:
                try:
                    await session.voice_client.move_to(voice_channel)
                except Exception as e:
                    log.error(f"Failed to move to VC for {session.username}: {e}")
        else:
            try:
                session.voice_client = await voice_channel.connect(timeout=20.0, reconnect=True)
            except Exception as e:
                log.error(f"Failed to connect to VC for {session.username}: {e}")
                return

        # 2. Start Playing
        if session.voice_client and session.voice_client.is_connected():
            hls_url = await self._get_hls_url(session.username)
            if hls_url:
                session.hls_url = hls_url
                try:
                    audio_source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(
                        hls_url,
                        before_options="-re -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
                        options="-vn"
                    ))
                    session.voice_client.play(
                        audio_source, 
                        after=lambda e: log.info(f"Stream ended for {session.username}: {e}")
                    )
                    log.info(f"Started playback for {session.username} in {voice_channel.name}")
                    
                    # Notify in text channel
                    embed = discord.Embed(
                        description=f"🔊 Started streaming **@{session.username}**'s live audio.",
                        color=discord.Color.green()
                    )
                    return embed
                except Exception as e:
                    log.error(f"FFmpeg play error for {session.username}: {e}")
        return None

    async def stop_voice(self, session: TikTokLiveSession):
        """Disconnects and cleans up voice resources."""
        if session.voice_client:
            try:
                if session.voice_client.is_playing():
                    session.voice_client.stop()
                await session.voice_client.disconnect(force=True)
            except Exception as e:
                log.error(f"Error disconnecting voice for {session.username}: {e}")
            session.voice_client = None
