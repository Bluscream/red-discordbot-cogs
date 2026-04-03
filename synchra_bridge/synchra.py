import asyncio
import logging
import discord
import time
from typing import Dict, Optional, List, Union, Any, Literal
from uuid import UUID

from redbot.core import Config, commands, checks
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import success, error, warning, info

from .session import SynchraSession
from .utils.api_manager import SynchraAPIManager
from .utils.ws_handler import SynchraWSHandler
from .voice_handler import SynchraVoiceHandler

log = logging.getLogger("red.blu.synchra_bridge")

class Synchra(commands.Cog):
    """Universal stream monitoring and synchronization using the Synchra API."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=928374565, force_registration=True)
        self.config.register_global(
            access_token=None,
            client_id=None,
            client_secret=None,
            monitored_channels={} # {uuid_str: {data}}
        )
        
        # Core Managers
        self.api = SynchraAPIManager(self.config)
        self.ws: Optional[SynchraWSHandler] = None
        self.voice = SynchraVoiceHandler(self.bot)
        
        # Runtime State
        self.active_sessions: Dict[str, SynchraSession] = {} # {uuid_str: session}
        self.ws_queue = asyncio.Queue()
        
        # Tasks
        self._main_loop_task: Optional[asyncio.Task] = None
        self._ws_event_task: Optional[asyncio.Task] = None
        self._initialized = False

    async def cog_load(self):
        """Initialize the cog and start background tasks."""
        if await self.api.initialize():
            # Initialize WS
            self.ws = SynchraWSHandler(self.api, self.ws_queue)
            await self.ws.start()
            
            # Start background tasks
            self._main_loop_task = self.bot.loop.create_task(self._main_monitor_loop())
            self._ws_event_task = self.bot.loop.create_task(self._process_ws_events())
            self._initialized = True
            log.info("SynchraBridge initialized.")
        else:
            log.warning("SynchraBridge loaded but credentials are missing. Use [p]synchra set to configure.")

    def cog_unload(self):
        """Cleanup resources on unload."""
        if self._main_loop_task:
            self._main_loop_task.cancel()
        if self._ws_event_task:
            self._ws_event_task.cancel()
        
        if self.ws:
            self.bot.loop.create_task(self.ws.stop())
        
        if self.api:
            self.bot.loop.create_task(self.api.close())
            
        # Cleanup all voice clients
        for session in self.active_sessions.values():
            if session.voice_client:
                self.bot.loop.create_task(self.voice.stop_voice(session))

    async def _process_ws_events(self):
        """Process real-time events from the WebSocket queue."""
        log.info("Synchra WS event processor started.")
        while True:
            try:
                event = await self.ws_queue.get()
                etype = event.get("type")
                channel_id = event.get("channel_id")
                
                if not channel_id or str(channel_id) not in self.active_sessions:
                    self.ws_queue.task_done()
                    continue
                
                session = self.active_sessions[str(channel_id)]
                
                if etype == "ws_status":
                    is_live = event.get("is_live", False)
                    if is_live:
                        # Fetch fresh providers for metadata
                        providers = await self.api.get_providers(session.channel_uuid)
                        await self._handle_go_live(session, providers)
                    else:
                        await self._handle_go_offline(session)
                
                elif etype == "ws_activity":
                    # Potentially handle follows/subs notifications here
                    pass
                
                elif etype == "chat_message":
                    # Handle chat synchronization
                    pass
                
                self.ws_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Error in WS event processor: {e}")
                await asyncio.sleep(1)

    async def _main_monitor_loop(self):
        """Main loop for status polling and session management (Fallback/Integrity check)."""
        log.info("Synchra main monitor loop started.")
        await self.bot.wait_until_ready()
        
        while True:
            try:
                if not self.api.is_ready:
                    await asyncio.sleep(60)
                    continue

                channels = await self.config.monitored_channels()
                for uuid_str, data in channels.items():
                    # 1. Ensure internal session exists
                    if uuid_str not in self.active_sessions:
                        session = SynchraSession(
                            channel_uuid=UUID(uuid_str),
                            display_name=data.get("display_name", "Unknown"),
                            platform=data.get("platform", "unknown"),
                            handle=data.get("handle", "unknown"),
                            text_channel_id=data.get("text_channel_id"),
                            voice_channel_id=data.get("voice_channel_id"),
                            webhook_url=data.get("webhook_url"),
                            voice_enabled=data.get("voice_enabled", True),
                            chat_enabled=data.get("chat_enabled", True),
                            last_live=data.get("last_live", 0)
                        )
                        self.active_sessions[uuid_str] = session
                        # Subscribe via WS
                        if self.ws:
                            await self.ws.subscribe(session.channel_uuid)

                    # 2. Check status (Integrity check / Fallback for WS failures)
                    session = self.active_sessions[uuid_str]
                    now = time.time()
                    
                    # Interval: Much longer if WS is active, otherwise fallback to polling
                    interval = 600 if (self.ws and self.ws._running) else 120
                    if now - session.last_status_check < interval:
                        continue
                    
                    session.last_status_check = now
                    try:
                        providers = await self.api.get_providers(session.channel_uuid)
                        is_currently_live = any(getattr(p, "is_live", False) for p in providers)
                        
                        if is_currently_live:
                            await self._handle_go_live(session, providers)
                        else:
                            await self._handle_go_offline(session)
                    except Exception as e:
                        log.error(f"Error checking status for {session.display_name}: {e}")

                await asyncio.sleep(10)
            except asyncio.CancelledError: break
            except Exception as e:
                log.error(f"Synchra main loop error: {e}")
                await asyncio.sleep(60)

    async def _handle_go_live(self, session: SynchraSession, providers: List[Any]):
        """Triggered when a channel goes live."""
        if session.last_notified_is_live is True: return
        
        session.is_live = True
        session.last_notified_is_live = True
        
        # Get live provider for metadata
        live_provider = next((p for p in providers if getattr(p, "is_live", False)), providers[0])
        title = getattr(live_provider, "title", "Live Broadcast")
        game = getattr(live_provider, "game_name", "")
        
        # Notify text channel
        description = f"**{session.display_name}** is now live!"
        if title: description += f"\n\n> {title}"
        if game: description += f"\n🎮 {game}"
        
        embed = discord.Embed(title="Stream Live!", description=description, color=discord.Color.red())
        if hasattr(live_provider, "thumbnail_url"):
            embed.set_image(url=getattr(live_provider, "thumbnail_url"))
            
        await self._send_notification(session, embed)
        
        # Start Voice Bridge
        if session.voice_enabled and session.voice_channel_id:
            session.hls_url = await self.api.get_hls_fallback(session.platform, session.handle)
            if session.hls_url:
                await self.voice.start_voice(session)

    async def _handle_go_offline(self, session: SynchraSession):
        """Triggered when a channel goes offline."""
        if session.last_notified_is_live is False: return
        
        session.is_live = False
        session.last_notified_is_live = False
        session.last_live = time.time()
        
        # Update config
        async with self.config.monitored_channels() as channels:
            if str(session.channel_uuid) in channels:
                channels[str(session.channel_uuid)]["last_live"] = session.last_live
        
        # Stop Voice Bridge
        if session.voice_client:
            await self.voice.stop_voice(session)
            
        await self._send_notification(session, f"⚫ **{session.display_name}** is now offline.")

    async def _send_notification(self, session: SynchraSession, content: Union[str, discord.Embed]):
        """Send a notification to the session's text channel."""
        target_channel = self.bot.get_channel(session.text_channel_id)
        if not target_channel: return
        
        try:
            if isinstance(content, discord.Embed):
                await target_channel.send(embed=content)
            else:
                await target_channel.send(content)
        except Exception as e:
            log.warning(f"Failed to send notification for {session.display_name}: {e}")

    @commands.hybrid_group(name="synchra", invoke_without_command=True)
    async def synchra_cmd(self, ctx):
        """Synchra Multi-Platform Monitoring."""
        if ctx.invoked_subcommand is not None: return
        await ctx.send_help()

    @synchra_cmd.command(name="monitor")
    @checks.admin_or_permissions(manage_guild=True)
    async def monitor(self, ctx, platform: str, handle: str, 
                      text_channel: discord.TextChannel,
                      voice_channel: Optional[discord.VoiceChannel] = None):
        """Start monitoring a channel via its platform-specific handle."""
        if not self.api.is_ready:
            return await ctx.send(error("Synchra API not configured. Use `[p]synchra set` first."))

        await ctx.typing()
        channel = await self.api.lookup_channel(platform, handle)
        if not channel:
            return await ctx.send(error(f"Could not find a Synchra channel for **{platform}** / **{handle}**.\nMake sure you've added this provider to your Synchra account."))

        uuid_str = str(channel.id)
        async with self.config.monitored_channels() as channels:
            channels[uuid_str] = {
                "display_name": channel.display_name,
                "platform": platform.lower(),
                "handle": handle,
                "text_channel_id": text_channel.id,
                "voice_channel_id": voice_channel.id if voice_channel else None,
                "voice_enabled": True if voice_channel else False,
                "chat_enabled": True,
                "last_live": 0
            }
        
        await ctx.send(success(f"Now monitoring **{channel.display_name}**! UUID: `{uuid_str}`"))

    @synchra_cmd.command(name="stop")
    @checks.admin_or_permissions(manage_guild=True)
    async def stop(self, ctx, channel_id_or_handle: str):
        """Stop monitoring a channel."""
        found_uuid = None
        async with self.config.monitored_channels() as channels:
            for uuid_str, data in channels.items():
                if uuid_str == channel_id_or_handle or data["handle"].lower() == channel_id_or_handle.lower():
                    found_uuid = uuid_str
                    break
            
            if found_uuid:
                del channels[found_uuid]
                if found_uuid in self.active_sessions:
                    session = self.active_sessions.pop(found_uuid)
                    if self.ws:
                        await self.ws.unsubscribe(session.channel_uuid)
                    if session.voice_client: 
                        await self.voice.stop_voice(session)
                return await ctx.send(success(f"Stopped monitoring channel."))
        
        await ctx.send(error(f"Channel not found in monitoring list."))

    @synchra_cmd.command(name="list")
    async def list(self, ctx):
        """List all monitored channels."""
        channels = await self.config.monitored_channels()
        if not channels:
            return await ctx.send("No channels are being monitored.")
            
        embed = discord.Embed(title="Monitored Synchra Channels", color=discord.Color.blue())
        for uuid_str, data in channels.items():
            session = self.active_sessions.get(uuid_str)
            status = "🔴 Live" if session and session.is_live else "⚫ Offline"
            value = f"Status: {status}\nPlatform: {data['platform'].capitalize()}\nHandle: `{data['handle']}`"
            embed.add_field(name=data["display_name"], value=value, inline=False)
        
        await ctx.send(embed=embed)

    @synchra_cmd.command(name="migrate")
    @checks.is_owner()
    async def migrate(self, ctx):
        """Automatically migrate streamers from the old stream_sync cog."""
        stream_sync_cog = self.bot.get_cog("StreamSync")
        if not stream_sync_cog:
            return await ctx.send(error("StreamSync cog not found. Make sure it is loaded."))

        if not self.api.is_ready:
            return await ctx.send(error("Synchra API not configured. Use `[p]synchra set` first."))

        await ctx.typing()
        old_streams = await stream_sync_cog.config.monitored_streams()
        count = 0
        failed = []

        for platform, channels in old_streams.items():
            for handle, data in channels.items():
                channel = await self.api.lookup_channel(platform, handle)
                if channel:
                    uuid_str = str(channel.id)
                    async with self.config.monitored_channels() as new_channels:
                        new_channels[uuid_str] = {
                            "display_name": channel.display_name,
                            "platform": platform,
                            "handle": handle,
                            "text_channel_id": data.get("text_channel_id"),
                            "voice_channel_id": data.get("voice_channel_id"),
                            "voice_enabled": data.get("voice_enabled", True),
                            "chat_enabled": data.get("chat_enabled", True),
                            "last_live": data.get("last_live", 0)
                        }
                    count += 1
                else:
                    failed.append(f"{platform}/{handle}")

        msg = f"Migrated **{count}** channels from StreamSync."
        if failed:
            msg += f"\n\nCould not find Synchra UUIDs for: {', '.join(failed[:10])}..."
            if len(failed) > 10: msg += f" (+{len(failed)-10} more)"
        
        await ctx.send(success(msg))

    @synchra_cmd.group(name="set")
    @checks.is_owner()
    async def synchra_set(self, ctx):
        """Configure Synchra API Credentials."""
        pass

    @synchra_set.command(name="token")
    async def set_token(self, ctx, token: str):
        """Set your Synchra Access Token."""
        await self.config.access_token.set(token)
        await ctx.message.delete()
        await ctx.send(success("Synchra Access Token updated."), delete_after=5)
        await self.api.initialize()

    @synchra_set.command(name="client")
    async def set_client(self, ctx, client_id: str, client_secret: str):
        """Set Synchra Client ID and Secret (for OAuth)."""
        await self.config.client_id.set(client_id)
        await self.config.client_secret.set(client_secret)
        await ctx.message.delete()
        await ctx.send(success("Synchra OAuth credentials updated."), delete_after=5)
        await self.api.initialize()
