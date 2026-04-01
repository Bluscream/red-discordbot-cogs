import asyncio
from typing import Optional
import logging
import yt_dlp
import discord
import aiohttp
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

    async def _set_identity(self, session: TikTokLiveSession, guild: discord.Guild):
        """Temporarily sets the bot's nickname and server avatar."""
        me = guild.me
        session.original_nick = me.nick
        
        # 1. Nickname
        new_nick = f"@{session.username}"[:32]
        try:
            await me.edit(nick=new_nick)
            log.info(f"Set bot nickname to {new_nick} in {guild.name}")
        except Exception as e:
            log.warning(f"Failed to set bot nickname: {e}")

        # 2. Server Avatar (Tier 2/Nitro)
        if session.client and hasattr(session.client, "room_info"):
            avatar_url = session.client.room_info.get("owner", {}).get("avatar_thumb", {}).get("url_list", [None])[0]
            if avatar_url:
                try:
                    async with aiohttp.ClientSession() as cs:
                        async with cs.get(avatar_url) as r:
                            if r.status == 200:
                                avatar_bytes = await r.read()
                                await me.edit(avatar=avatar_bytes)
                except Exception as e:
                    log.warning(f"Failed to set server avatar: {e}")

    async def _revert_identity(self, session: TikTokLiveSession):
        """Reverts the bot's identity to original state."""
        if not session.voice_client:
            return
        guild = session.voice_client.guild
        me = guild.me
        
        try:
            await me.edit(nick=session.original_nick, avatar=None)
            log.info(f"Reverted bot identity in {guild.name}")
        except Exception as e:
            log.warning(f"Failed to revert bot identity: {e}")

    async def start_voice(self, session: TikTokLiveSession):
        """Connects to the voice channel and starts playing the TikTok stream."""
        voice_channel = self.bot.get_channel(session.voice_channel)
        if not voice_channel:
            log.error(f"Voice channel {session.voice_channel} not found.")
            return

        # 1. Connect or Move
        current_vc = session.voice_client or voice_channel.guild.voice_client
        
        if current_vc and current_vc.is_connected():
            session.voice_client = current_vc
            if current_vc.channel.id != voice_channel.id:
                try:
                    await current_vc.move_to(voice_channel)
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
                    
                    # 3. Identity & Status Sync
                    await self._set_identity(session, voice_channel.guild)
                    try:
                        # Fetch current viewers if available
                        viewers = getattr(session.client, 'viewer_count', 0)
                        await voice_channel.edit(status=f"🔴 Live with {viewers} viewers")
                    except Exception as e:
                        log.warning(f"Failed to set VC status: {e}")

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
                
                # Revert Identity & Status
                await self._revert_identity(session)
                try:
                    await session.voice_client.channel.edit(status="⚫ Offline")
                except: pass

                await session.voice_client.disconnect(force=True)
            except Exception as e:
                log.error(f"Error disconnecting voice for {session.username}: {e}")
            session.voice_client = None
