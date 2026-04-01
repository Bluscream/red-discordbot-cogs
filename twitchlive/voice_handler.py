import asyncio
from typing import Optional
import logging
import yt_dlp
import discord
import aiohttp
from redbot.core.bot import Red
from .session import TwitchLiveSession
from .utils.action_queue import ActionQueue

log = logging.getLogger("red.blu.twitchlive.voice")

class TwitchVoiceHandler:
    def __init__(self, bot: Red, action_queue: ActionQueue):
        self.bot = bot
        self.action_queue = action_queue

    async def _get_hls_url(self, username: str) -> Optional[str]:
        """Extract HLS stream URL using yt-dlp."""
        ydl_opts = {
            'format': 'best',
            'quiet': True,
            'no_warnings': True,
        }
        url = f"https://www.twitch.tv/{username}"
        try:
            # Need to provide some user-agent or twitch specific opts if needed, 
            # but yt-dlp usually handles Twitch well.
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await asyncio.to_thread(ydl.extract_info, url, download=False)
                return info.get('url')
        except Exception as e:
            log.error(f"yt-dlp failed to extract HLS for {username}: {e}")
            return None

    async def _set_identity(self, session: TwitchLiveSession, guild: discord.Guild):
        """Temporarily sets the bot's nickname and server avatar to match the Twitch streamer."""
        me = guild.me
        session.original_nick = me.nick
        
        # 1. Nickname
        new_nick = f"@{session.username}"[:32]
        await self.action_queue.put({
            "type": "identity",
            "payload": {"guild": guild, "nick": new_nick}
        })

        # 2. Server Avatar (requires session.avatar_url from the API)
        if session.avatar_url:
            async def _fetch_and_set_avatar():
                try:
                    async with aiohttp.ClientSession() as cs:
                        async with cs.get(session.avatar_url) as r:
                            if r.status == 200:
                                avatar_bytes = await r.read()
                                await self.action_queue.put({
                                    "type": "identity",
                                    "payload": {"guild": guild, "avatar_bytes": avatar_bytes}
                                })
                except Exception as e:
                    log.warning(f"Failed to fetch {session.username} avatar: {e}")
            
            await self.action_queue.put({
                "type": "callback",
                "payload": {"func": _fetch_and_set_avatar}
            })

    async def _revert_identity(self, session: TwitchLiveSession):
        """Reverts the bot's identity to original state."""
        if not session.voice_client:
            return
        guild = session.voice_client.guild
        await self.action_queue.put({
            "type": "identity",
            "payload": {"guild": guild, "nick": session.original_nick, "avatar_bytes": None}
        })

    async def start_voice(self, session: TwitchLiveSession):
        """Connects to the voice channel and starts playing the Twitch stream."""
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
                    log.error(f"Failed to move to VC for {session.username}: {e}")
        else:
            try:
                session.voice_client = await voice_channel.connect(timeout=20.0, reconnect=True)
            except Exception as e:
                log.error(f"Failed to connect to VC for {session.username}: {e}")
                return

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
                    if session.voice_client.is_playing():
                        session.voice_client.stop()
                        
                    session.voice_client.play(
                        audio_source, 
                        after=lambda e: log.info(f"Twitch stream ended for {session.username}: {e}")
                    )
                    log.info(f"Started playback for {session.username} in {voice_channel.name}")
                    
                    # Identity & Status
                    await self._set_identity(session, voice_channel.guild)
                    await self.action_queue.put({
                        "type": "status",
                        "payload": {"channel": voice_channel, "text": "🔴 Twitch Live"}
                    })

                    embed = discord.Embed(
                        description=f"🔊 Started streaming **{session.username}**'s live audio from Twitch.",
                        color=discord.Color.purple()
                    )
                    return embed
                except Exception as e:
                    log.error(f"FFmpeg play error for {session.username}: {e}")
        return None

    async def stop_voice(self, session: TwitchLiveSession):
        """Disconnects and cleans up voice resources."""
        if session.voice_client:
            try:
                if session.voice_client.is_playing():
                    session.voice_client.stop()
                
                await self._revert_identity(session)
                await self.action_queue.put({
                    "type": "status",
                    "payload": {"channel": session.voice_client.channel, "text": "⚫ Offline"}
                })
                await session.voice_client.disconnect(force=True)
            except Exception as e:
                log.error(f"Error disconnecting Twitch voice for {session.username}: {e}")
            session.voice_client = None
