import asyncio
import logging
from typing import Optional, Any
import discord
from redbot.core.bot import Red
from .session import SynchraSession

log = logging.getLogger("red.blu.synchra.voice")

class SynchraVoiceHandler:
    """Handles FFmpeg audio streaming to Discord voice channels for Synchra sessions."""
    
    def __init__(self, bot: Red, action_queue: Any):
        self.bot = bot
        self.action_queue = action_queue

    async def start_voice(self, session: SynchraSession):
        """Connect to voice and start the HLS stream."""
        voice_channel = self.bot.get_channel(session.voice_channel_id)
        if not voice_channel:
            log.warning(f"Voice channel {session.voice_channel_id} not found for {session.display_name}")
            return

        # Ensure connection
        try:
            if session.voice_client and session.voice_client.is_connected():
                if session.voice_client.channel.id != voice_channel.id:
                    await session.voice_client.move_to(voice_channel)
            else:
                session.voice_client = await voice_channel.connect(timeout=20.0, reconnect=True)
        except Exception as e:
            log.error(f"Failed to connect to voice for {session.display_name}: {e}")
            return

        if not session.hls_url:
            log.warning(f"No HLS URL found for {session.display_name}. Voice bridge aborted.")
            return

        # Start playback
        try:
            # -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 for stability
            audio_source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(
                session.hls_url,
                before_options="-re -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
                options="-vn"
            ))
            
            if session.voice_client.is_playing():
                session.voice_client.stop()
            
            session.voice_client.play(audio_source)
            log.info(f"Started voice bridge for {session.display_name} in {voice_channel.name}")
            
            # Identity synchronization (Optional, but nice for branding)
            # await self._sync_identity(session, voice_channel.guild)
            
            return discord.Embed(
                description=f"🔊 Now streaming audio from **{session.display_name}**.",
                color=discord.Color.green()
            )
        except Exception as e:
            log.error(f"FFmpeg error for {session.display_name}: {e}")
            return None

    async def stop_voice(self, session: SynchraSession):
        """Stop playback and disconnect from voice."""
        if session.voice_client:
            try:
                if session.voice_client.is_playing():
                    session.voice_client.stop()
                await session.voice_client.disconnect(force=True)
                log.info(f"Stopped voice bridge for {session.display_name}")
            except Exception as e:
                log.error(f"Error disconnecting voice for {session.display_name}: {e}")
            session.voice_client = None
