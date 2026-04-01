import asyncio
import logging
import discord
import time
from typing import Dict, Optional, List, Union, Any, Literal

from redbot.core import Config, commands, checks
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import success, error, warning, info

from .session import StreamSession
from .voice_handler import UnifiedVoiceHandler
from .utils.action_queue import ActionQueue
from .utils.retry import StaggeredRetry
from .utils.webhooks import delete_webhook_by_url, ensure_webhook
from .utils.formatting import format_status_embed
from .utils.normalization import normalize_channel_id

# Import Platforms
from .platforms.tiktok import TikTokPlatform
from .platforms.twitch import TwitchPlatform
from .platforms.youtube import YoutubePlatform

log = logging.getLogger("red.blu.stream_sync")

class StreamSync(commands.Cog):
    """Unify monitoring of TikTok, Twitch, and YouTube Live into one modular cog."""

    def __init__(self, bot: Red):
        log.info("\n" + "="*50 + "\n" + "StreamSync Cog Initializing...".center(50) + "\n" + "="*50)
        self.bot = bot
        self.config = Config.get_conf(self, identifier=928374564, force_registration=True)
        self.config.register_global(
            twitch_client_id=None,
            twitch_client_secret=None,
            tiktok_session_id=None,
            tiktok_tt_target_idc=None,
            twitch_irc_nick=None,
            twitch_irc_password=None,
            monitored_streams={} # {platform: {id: data}}
        )
        
        # Configuration Constants
        self.LIVE_STATUS_CHECK_INTERVAL = 300.0  # 5 minutes for active streams
        
        # Runtime State
        self.active_sessions: Dict[str, Dict[str, StreamSession]] = {
            "tiktok": {}, "twitch": {}, "youtube": {}
        }
        
        # Universal Action Queue
        self.action_queue = ActionQueue(self.bot)
        
        # Unified Voice Handler
        self.voice_handler = UnifiedVoiceHandler(bot, self.action_queue)
        
        # Platform Instances
        self.platforms = {
            "tiktok": TikTokPlatform(bot, self.action_queue, self.config, self),
            "twitch": TwitchPlatform(bot, self.action_queue, self.config, self),
            "youtube": YoutubePlatform(bot, self.action_queue, self.config, self)
        }
        
        # Cog-Specific Action Handlers
        self.action_queue.register_handler("voice_connect", self._handle_voice_connect)
        self.action_queue.register_handler("voice_disconnect", self._handle_voice_disconnect)
        self.action_queue.register_handler("chat_message", self._handle_chat_message)
        self.action_queue.register_handler("prune_webhook", self._handle_prune_webhook)
        self.action_queue.start()
        
        self.main_loop_task = None

    async def cog_load(self):
        self.main_loop_task = self.bot.loop.create_task(self._main_monitor_loop())

    def cog_unload(self):
        if self.main_loop_task:
            self.main_loop_task.cancel()
        
        self.bot.loop.create_task(self.action_queue.stop())
        
        # Cleanup all sessions
        for p in self.active_sessions:
            for s in list(self.active_sessions[p].values()):
                self.bot.loop.create_task(self._stop_session(s))

    async def _handle_voice_connect(self, payload: dict):
        session = payload.get("session")
        if session and not session.voice_client:
            voice_embed = await self.voice_handler.start_voice(session)
            if voice_embed and session.text_channel:
                await self.action_queue.put({"type": "message", "payload": {"target": session.text_channel, "content": voice_embed}})

    async def _handle_voice_disconnect(self, payload: dict):
        session = payload.get("session")
        if session:
            await self.voice_handler.stop_voice(session)

    async def _handle_chat_message(self, payload: dict):
        """Standardized handler for all incoming platform chat messages."""
        target = payload.get("target")
        author = payload.get("author")
        message = payload.get("message")
        platform = payload.get("platform", "unknown")
        
        if target and author and message:
            fmt_msg = f"**[{platform.capitalize()}]** **{author}**: {message}"
            await self.action_queue.put({"type": "message", "payload": {"target": target, "content": fmt_msg}})

    async def _handle_prune_webhook(self, payload: dict):
        """Automatic cleanup and self-healing for deleted webhooks."""
        url = payload.get("url")
        if not url: return
        
        log.warning(f"Pruning deleted webhook: {url[:55]}...")
        
        async with self.config.monitored_streams() as streams:
            for platform in streams:
                for cid in list(streams[platform].keys()):
                    data = streams[platform][cid]
                    if data.get("text_channel") == url:
                        # Before clearing, check if we should recreate
                        is_managed = data.get("is_managed", False)
                        txt_chan_id = data.get("text_channel_id")
                        
                        # Clear it in config
                        data["text_channel"] = None
                        
                        # Try to find the channel for recreation
                        channel = self.bot.get_channel(txt_chan_id)
                        if is_managed and channel:
                            from .utils.webhooks import ensure_webhook, clear_webhook_cache
                            clear_webhook_cache(txt_chan_id)
                            new_url = await ensure_webhook(channel)
                            if new_url:
                                data["text_channel"] = new_url
                                log.info(f"Recreated managed webhook for {platform} @{cid}: {new_url[:55]}...")
                            else:
                                data["is_managed"] = False
                                log.warning(f"Failed to recreate managed webhook for {platform} @{cid}. Reverting to direct messages.")
                        else:
                            data["is_managed"] = False
                            log.info(f"Cleared dead webhook for {platform} @{cid}")
                        
                        # Sync to active session
                        session = self.active_sessions.get(platform, {}).get(cid)
                        if session:
                            session.text_channel = data["text_channel"]
                            session.is_managed = data["is_managed"]
                        
                        log.info(f"Automatically cleared dead webhook for {platform} @{cid}")

    async def _handle_go_live(self, platform_name: str, cid: str, status: Dict[str, Any]):
        """Unified logic for when a stream goes live."""
        session = self.active_sessions.get(platform_name, {}).get(cid)
        if not session or session.last_notified_is_live is True: return
        
        session.is_live = True
        session.last_notified_is_live = True
        session.last_notified_title = status.get("title")
        session.last_notified_game = status.get("extra")
        
        handler = self.platforms.get(platform_name)
        
        # Reset retry for next offline period
        async with self.config.monitored_streams() as ms:
            if platform_name in ms and cid in ms[platform_name]:
                # We could store more state here if needed
                pass

        meta = await handler.get_metadata(cid)
        session.avatar_url = meta.get("avatar_url")
        
        if session.chat_enabled:
            embed = format_status_embed(platform_name, cid, status.get("title", ""), 
                extra=status.get("extra"), viewers=status.get("viewers", 0),
                thumbnail_url=status.get("thumbnail"))
            await self.action_queue.put({"type": "message", "payload": {"target": session.text_channel, "content": embed}})
            await handler.start_chat(session)
        
        if session.voice_enabled:
            # Fetch the actual HLS URL for audio playback
            session.hls_url = await handler.get_hls_url(cid)
            if session.hls_url:
                await self.action_queue.put({"type": "voice_connect", "payload": {"session": session}})
            else:
                log.warning(f"Could not extract HLS URL for {platform_name} @{cid}. Voice bridge skipped.")

    async def _handle_go_offline(self, platform_name: str, cid: str):
        """Unified logic for when a stream goes offline."""
        session = self.active_sessions.get(platform_name, {}).get(cid)
        if not session or session.last_notified_is_live is False: return
        
        session.is_live = False
        session.last_notified_is_live = False
        session.last_live = time.time()
        handler = self.platforms.get(platform_name)

        # Persist last_live
        async with self.config.monitored_streams() as ms:
            if platform_name in ms and cid in ms[platform_name]:
                ms[platform_name][cid]["last_live"] = session.last_live
                
        if session.chat_enabled:
            await self.action_queue.put({"type": "message", "payload": {"target": session.text_channel, "content": f"⚫ **{cid}** is now offline on {platform_name.capitalize()}."}})
            await handler.stop_chat(cid)
        
        if session.voice_enabled:
            await self.action_queue.put({"type": "voice_disconnect", "payload": {"session": session}})

    async def _main_monitor_loop(self):
        """Unified background polling for all platforms."""
        log.info("StreamSync main monitor loop started.")
        retries: Dict[str, Dict[str, StaggeredRetry]] = {"twitch": {}, "youtube": {}, "tiktok": {}}
        
        await self.bot.wait_until_ready()
        
        while True:
            try:
                streams = await self.config.monitored_streams()
                for platform_name, channels in streams.items():
                    handler = self.platforms.get(platform_name)
                    if not handler: continue
                    
                    for cid, data in channels.items():
                        if cid not in self.active_sessions[platform_name]:
                            txt_chan = data.get("text_channel") or data.get("text_channel_id")
                            session = StreamSession(
                                platform_name, cid, data["voice_channel"], txt_chan,
                                voice_enabled=data.get("voice_enabled", True),
                                chat_enabled=data.get("chat_enabled", True),
                                last_live=data.get("last_live", 0)
                            )
                            if data.get("is_managed"): session.is_managed = True
                            self.active_sessions[platform_name][cid] = session
                            retry = StaggeredRetry()
                            retries[platform_name][cid] = retry
                            if platform_name == "tiktok": await handler.start_monitor(session, retry=retry)

                        session = self.active_sessions[platform_name][cid]
                        retry = retries[platform_name][cid]
                        
                        if platform_name in ["twitch", "youtube"]:
                            now = self.bot.loop.time()
                            
                            # Decide on current wait interval
                            interval = retry.current if not session.is_live else self.LIVE_STATUS_CHECK_INTERVAL
                            
                            if now < session.last_status_check + interval:
                                continue
                                
                            try:
                                log.info(f"Checking status for {platform_name} @{cid} (Interval: {int(interval)}s)...")
                                status = await handler.is_live(cid)
                                session.last_status_check = now
                                if not status.get("live"):
                                    # If offline, slowly increment the polling interval
                                    retry.failures += 1
                                    retry.current = min(retry.current * retry.multiplier, retry.max_val)
                                else:
                                    # If live, reset the interval for next time
                                    retry.reset()
                            except Exception as e:
                                log.error(f"Error checking status for {platform_name} @{cid}: {e}")
                                await retry.sleep() # Wait more on actual API errors
                                continue
                            
                            if status.get("live"):
                                session.current_viewers = status.get("viewers", 0)
                                # Only notify if status changed OR title/category changed
                                if not session.last_notified_is_live or \
                                   status.get("title") != session.last_notified_title or \
                                   status.get("extra") != session.last_notified_game:
                                    await self._handle_go_live(platform_name, cid, status)
                            else:
                                if session.last_notified_is_live is not False:
                                    await self._handle_go_offline(platform_name, cid)

                await asyncio.sleep(10)
            except asyncio.CancelledError: break
            except Exception as e:
                log.error(f"Main Loop error: {e}")
                await asyncio.sleep(60)

    async def _stop_session(self, session: StreamSession):
        p_name = session.platform
        handler = self.platforms.get(p_name)
        if handler:
            if p_name == "tiktok": await handler.stop_monitor(session.channel_id)
            await handler.stop_chat(session.channel_id)
            
        if session.voice_client: await self.voice_handler.stop_voice(session)
        if session.is_managed and session.text_channel: await delete_webhook_by_url(session.text_channel)
        if session.channel_id in self.active_sessions[p_name]: del self.active_sessions[p_name][session.channel_id]

    async def platform_autocomplete(self, interaction: discord.Interaction, current: str):
        return [discord.app_commands.Choice(name=p.capitalize(), value=p) for p in self.platforms.keys() if current.lower() in p.lower()]

    @commands.hybrid_group(name="streams", invoke_without_command=True)
    async def streams_cmd(self, ctx):
        """StreamSync Commands. Bare use shows active bridges for this channel."""
        if ctx.invoked_subcommand is not None: return

        streams = await self.config.monitored_streams()
        relevant = []
        for p, channels in streams.items():
            for cid, data in channels.items():
                if data.get("text_channel_id") == ctx.channel.id:
                    session = self.active_sessions.get(p, {}).get(cid)
                    is_live = session and session.is_live
                    
                    v_ico = "🔊" if data.get("voice_enabled", True) else "🔇"
                    c_ico = "💬" if data.get("chat_enabled", True) else "🔕"
                    icons = f"[{v_ico}{c_ico}]"
                    
                    if is_live:
                        viewers = getattr(session, "current_viewers", 0)
                        status_str = f"🔴 **Live** ({viewers} Viewers)"
                        relevant.append(f"{status_str} **{cid}** ({p.capitalize()}) {icons}")
                    else:
                        last_live = data.get("last_live", 0)
                        last_seen = f" - Last seen <t:{int(last_live)}:R>" if last_live > 0 else ""
                        relevant.append(f"⚫ **Offline** **{cid}** ({p.capitalize()}) {icons}{last_seen}")

        if relevant:
            embed = discord.Embed(
                title=f"Synced Streams in #{ctx.channel.name}", 
                description="\n".join(relevant), 
                color=discord.Color.green()
            )
            # embed.set_footer(text="StreamSync Bridge • Real-time Monitoring")
            await ctx.send(embed=embed)

    @streams_cmd.command(name="monitor")
    @checks.admin_or_permissions(manage_guild=True)
    @discord.app_commands.describe(platform="tiktok, twitch, or youtube", channel_id="Channel ID")
    async def monitor(self, ctx, platform: str, channel_id: str, 
                      voice_channel: Union[discord.VoiceChannel, discord.StageChannel], 
                      text_target: Union[discord.TextChannel, discord.VoiceChannel, discord.Thread]):
        """Monitor a stream. Requires Manage Server."""
        platform = platform.lower()
        if platform not in self.platforms: return await ctx.send(error(f"Unsupported platform."))
        
        channel_id = normalize_channel_id(platform, channel_id)
        webhook_url = await ensure_webhook(text_target, name=f"@{channel_id}")
        if not webhook_url: return await ctx.send(error("Webhook setup failed."))

        async with self.config.monitored_streams() as streams:
            if platform not in streams: streams[platform] = {}
            streams[platform][channel_id] = {
                "voice_channel": voice_channel.id,
                "text_channel": webhook_url,
                "text_channel_id": text_target.id,
                "is_managed": True,
                "voice_enabled": True,
                "chat_enabled": True,
                "last_live": 0
            }
        await ctx.send(success(f"Monitoring **{channel_id}** on **{platform.capitalize()}**."))

    @monitor.autocomplete("platform")
    async def monitor_platform_ac(self, interaction, current): return await self.platform_autocomplete(interaction, current)

    @streams_cmd.command(name="toggle")
    @checks.admin_or_permissions(manage_guild=True)
    async def toggle(self, ctx, platform: str, channel_id: str, feature: Literal["voice", "chat"]):
        """Toggle features for a streamer. Requires Manage Server."""
        platform = platform.lower()
        channel_id = normalize_channel_id(platform, channel_id)
        async with self.config.monitored_streams() as streams:
            if platform not in streams or channel_id not in streams[platform]: return await ctx.send(error("Channel not found."))
            new_val = not streams[platform][channel_id].get(f"{feature}_enabled", True)
            streams[platform][channel_id][f"{feature}_enabled"] = new_val
            if platform in self.active_sessions and channel_id in self.active_sessions[platform]:
                setattr(self.active_sessions[platform][channel_id], f"{feature}_enabled", new_val)
        await ctx.send(success(f"{feature.capitalize()} for **{channel_id}** is now **{'enabled' if new_val else 'disabled'}**."))

    @toggle.autocomplete("platform")
    async def toggle_platform_ac(self, interaction, current): return await self.platform_autocomplete(interaction, current)

    @streams_cmd.command(name="stop")
    @checks.admin_or_permissions(manage_guild=True)
    async def stop(self, ctx, platform: str, channel_id: str):
        """Stop monitoring a stream. Requires Manage Server."""
        platform = platform.lower()
        channel_id = normalize_channel_id(platform, channel_id)
        async with self.config.monitored_streams() as streams:
            if platform in streams and channel_id in streams[platform]:
                if platform in self.active_sessions and channel_id in self.active_sessions[platform]:
                    await self._stop_session(self.active_sessions[platform][channel_id])
                del streams[platform][channel_id]
                return await ctx.send(success(f"Stopped monitoring **{channel_id}**."))
        await ctx.send(error("Channel not found."))

    @stop.autocomplete("platform")
    async def stop_platform_ac(self, interaction, current): return await self.platform_autocomplete(interaction, current)

    @streams_cmd.command(name="list")
    @checks.admin_or_permissions(manage_guild=True)
    async def list(self, ctx):
        """List all monitored streams. Requires Manage Server."""
        streams = await self.config.monitored_streams()
        if not streams: return await ctx.send("No streams monitored.")
        embed = discord.Embed(title="Global StreamSync Status", color=discord.Color.blue())
        for platform, channels in streams.items():
            value = "\n".join([f"{'🔴' if cid in self.active_sessions[platform] and self.active_sessions[platform][cid].is_live else '⚫'} `{cid}` [{'🔊' if d.get('voice_enabled', True) else '🔇'}{'💬' if d.get('chat_enabled', True) else '🔕'}]" for cid, d in channels.items()])
            if value: embed.add_field(name=platform.capitalize(), value=value, inline=False)
        await ctx.send(embed=embed)

    @streams_cmd.group(name="set")
    @checks.is_owner()
    async def streamset(self, ctx):
        """Configure StreamSync (Owner Only)."""
        pass

    @streamset.command(name="toggle")
    async def bulk_toggle(self, ctx, platform: str, feature: Literal["voice", "chat"], state: bool):
        """Bulk toggle platform features."""
        platform = platform.lower()
        async with self.config.monitored_streams() as streams:
            if platform not in streams: return await ctx.send(warning(f"No streams for {platform}."))
            for cid in streams[platform]:
                streams[platform][cid][f"{feature}_enabled"] = state
                if platform in self.active_sessions and cid in self.active_sessions[platform]:
                    setattr(self.active_sessions[platform][cid], f"{feature}_enabled", state)
        await ctx.send(success(f"**{'Enabled' if state else 'Disabled'}** {feature} for all {platform.capitalize()} streams."))

    @bulk_toggle.autocomplete("platform")
    async def bt_platform_ac(self, interaction, current): return await self.platform_autocomplete(interaction, current)

    @streamset.command(name="twitch")
    async def set_twitch(self, ctx, client_id: str, client_secret: str):
        """Set Twitch Helix API credentials."""
        await self.config.twitch_client_id.set(client_id)
        await self.config.twitch_client_secret.set(client_secret)
        try: await ctx.message.delete()
        except: pass
        await ctx.send(success("Twitch Helix credentials updated."))

    @streamset.command(name="twitchchat")
    async def set_twitch_chat(self, ctx, nickname: str, token: str):
        """Set Twitch IRC credentials for chat sync."""
        await self.config.twitch_irc_nick.set(nickname)
        await self.config.twitch_irc_password.set(token if token.startswith("oauth:") else f"oauth:{token}")
        try: await ctx.message.delete()
        except: pass
        await ctx.send(success("Twitch IRC credentials updated."))

    @streamset.command(name="tiktok")
    async def set_tiktok(self, ctx, session_id: str, tt_target_idc: str):
        """Set TikTok Session ID and TT Target IDC."""
        await self.config.tiktok_session_id.set(session_id)
        await self.config.tiktok_tt_target_idc.set(tt_target_idc)
        try: await ctx.message.delete()
        except: pass
        await ctx.send(success(f"TikTok session credentials updated (IDC: `{tt_target_idc}`)."))
