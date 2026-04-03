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
from .utils.webhooks import ensure_webhook, send_webhook_message
from .utils.formatting import sanitize_mentions, clean_name
from .utils.action_queue import SynchraActionQueue
from .utils.retry import StaggeredRetry
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
        self.voice = SynchraVoiceHandler(self.bot)
        self.action_queue = SynchraActionQueue(bot, self.api, self.voice)
        self.monitor_retry = StaggeredRetry(start=60.0, multiplier=1.2, max_val=1800.0)
        self.ws: Optional[SynchraWSHandler] = None
        
        # Runtime State
        self.active_sessions: Dict[str, SynchraSession] = {} # {uuid_str: session}
        self.ws_queue = asyncio.Queue()
        self.user_provider_id: Optional[UUID] = None # Sender for chat mirroring
        
        # Tasks
        self._main_loop_task: Optional[asyncio.Task] = None
        self._ws_event_task: Optional[asyncio.Task] = None
        self._initialized = False

    async def cog_load(self):
        """Initialize the cog and start background tasks."""
        if await self.api.initialize():
            self.monitor_retry.reset()
            # Resolve user provider for outgoing chat
            user_providers = await self.api.get_user_providers()
            if user_providers:
                self.user_provider_id = UUID(user_providers[0]['id'])
                log.info(f"Resolved user_provider_id: {self.user_provider_id}")
            else:
                log.warning("No linked providers found for Synchra account. Outgoing chat disabled.")

            # Initialize WS
            self.action_queue.start()
            self.ws = SynchraWSHandler(self.api, self.ws_queue)
            await self.ws.start()
            
            # Initialize sessions from config
            monitored = await self.config.monitored_channels()
            for uuid_str, data in monitored.items():
                session = SynchraSession(
                    channel_uuid=UUID(uuid_str),
                    display_name=data.get("display_name", "Unknown"),
                    text_channel_id=data.get("text_channel_id"),
                    voice_channel_id=data.get("voice_channel_id"),
                    webhook_url=data.get("webhook_url"),
                    voice_enabled=data.get("voice_enabled", True),
                    chat_enabled=data.get("chat_enabled", True),
                    last_live=data.get("last_live", 0)
                )
                self.active_sessions[uuid_str] = session
                
                # Try to resolve/re-create webhook if missing
                if session.text_channel_id and not session.webhook_url:
                    channel = self.bot.get_channel(session.text_channel_id)
                    if channel and isinstance(channel, discord.TextChannel):
                        session.webhook_url = await ensure_webhook(channel)

                # Eagerly load providers for platform metadata
                session.providers = await self.api.get_providers(session.channel_uuid)

                if self.ws:
                    await self.ws.subscribe(session.channel_uuid)

            # Fetch and log Synchra user profile info
            user_info = await self.api.get_user_info()
            if user_info:
                username = user_info.get("username", "Unknown")
                uid = user_info.get("id", "Unknown")
                log.info(f"Authenticated with Synchra as: {username} ({uid})")

            # Start background tasks
            self._main_loop_task = self.bot.loop.create_task(self._main_monitor_loop())
            self._ws_event_task = self.bot.loop.create_task(self._process_ws_events())
            self._initialized = True
            log.info(f"SynchraBridge initialized. Monitoring {len(self.active_sessions)} channels.")
        else:
            log.warning("SynchraBridge loaded but credentials missing. Use [p]synchra set.")

    def cog_unload(self):
        """Cleanup resources on unload."""
        if self._main_loop_task:
            self._main_loop_task.cancel()
        if self._ws_event_task:
            self._ws_event_task.cancel()
        
        # Stop Action Queue
        self.bot.loop.create_task(self.action_queue.stop())
        
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
                data = event.get("data", {})
                
                if etype == "ws_status":
                    is_live = data.get("is_live", False)
                    if is_live:
                        # Fetch fresh providers for metadata
                        session.providers = await self.api.get_providers(session.channel_uuid)
                        await self._handle_go_live(session, session.providers)
                    else:
                        await self._handle_go_offline(session)
                
                elif etype == "chat_message":
                    # incoming chat mirroring
                    await self._mirror_chat_incoming(session, data)
                
                elif etype == "activity":
                    # Handle status and activity updates
                    pass
                
                self.ws_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Error in WS event processor: {e}")
                await asyncio.sleep(1)

    async def _mirror_chat_incoming(self, session: SynchraSession, data: Dict):
        """Relay platform chat to Discord using webhooks or standard messages."""
        if not session.chat_enabled or not session.text_channel_id:
            return
            
        channel = self.bot.get_channel(session.text_channel_id)
        if not channel: return

        # Format: [Platform] User: Message
        provider = data.get('provider', 'synchra')
        if hasattr(provider, 'value'): provider = provider.value
        
        user = clean_name(data.get('viewer_display_name', 'System'))
        avatar = data.get('viewer_avatar_url')
        
        # Extract message text from parts for better formatting
        parts = data.get('message_parts', [])
        content = "".join([p.get('text', '') for p in parts]) or data.get('message', '')
        
        if content:
            content = sanitize_mentions(content)
            # Use Webhook if available
            if session.webhook_url:
                await self.action_queue.put({
                    "type": "webhook",
                    "payload": {
                        "url": session.webhook_url,
                        "content": content,
                        "nick": f"[{str(provider).capitalize()}] {user}",
                        "avatar": avatar
                    }
                })
            else:
                await self.action_queue.put({
                    "type": "message",
                    "payload": {
                        "target": session.text_channel_id,
                        "content": f"**[{str(provider).capitalize()}]** {user}: {content}"
                    }
                })

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Handle Discord to Platform chat mirroring."""
        if not self._initialized or not self.user_provider_id:
            return
        if message.author.bot or message.content.startswith("!"):
            return
            
        # Check if this message is in a monitored channel
        for session in self.active_sessions.values():
            if message.channel.id == session.text_channel_id:
                if not session.chat_enabled:
                    continue
                
                # Forward to all active providers via Synchra Broadcast
                await self.action_queue.put({
                    "type": "synchra_broadcast",
                    "payload": {
                        "channel_id": str(session.channel_uuid),
                        "message": f"[{message.author.display_name}] {message.clean_content}",
                        "user_provider_id": str(self.user_provider_id)
                    }
                })
                break

    async def _main_monitor_loop(self):
        """Main loop for status polling and session management (Fallback/Integrity check)."""
        log.info("Synchra main monitor loop started.")
        await self.bot.wait_until_ready()
        
        while True:
            try:
                if not self.api.is_ready:
                    await self.monitor_retry.sleep()
                    continue

                channels = await self.config.monitored_channels()
                for uuid_str, data in channels.items():
                    # 1. Ensure internal session exists
                    if uuid_str not in self.active_sessions:
                        # ... initialization already handled in cog_load or monitor command ...
                        pass
                    
                    session = self.active_sessions.get(uuid_str)
                    if not session: continue

                    # 2. Heal Webhooks
                    if session.text_channel_id and not session.webhook_url:
                        channel = self.bot.get_channel(session.text_channel_id)
                        if channel and isinstance(channel, discord.TextChannel):
                            session.webhook_url = await ensure_webhook(channel)
                            if session.webhook_url:
                                async with self.config.monitored_channels() as cfg_channels:
                                    if uuid_str in cfg_channels:
                                        cfg_channels[uuid_str]["webhook_url"] = session.webhook_url

                    # 3. Check status
                    session = self.active_sessions[uuid_str]
                    now = time.time()
                    
                    # Interval: Much longer if WS is active, otherwise fallback to polling
                    interval = 600 if (self.ws and self.ws._running) else 120
                    if now - session.last_status_check < interval:
                        continue
                    
                    session.last_status_check = now
                    try:
                        session.providers = await self.api.get_providers(session.channel_uuid)
                        is_currently_live = session.is_currently_live
                        
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
        title = sanitize_mentions(getattr(live_provider, "title", "Live Broadcast"))
        game = sanitize_mentions(getattr(live_provider, "game_name", ""))
        
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
            # Pick first provider for HLS if possible, or fallback
            platform = getattr(live_provider.provider, 'value', str(live_provider.provider)).lower()
            handle = getattr(live_provider, 'provider_channel_name', session.display_name)
            
            session.hls_url = await self.api.get_hls_fallback(platform, handle)
            if session.hls_url:
                await self.action_queue.put({
                    "type": "voice_connect",
                    "payload": {"session": session}
                })

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
            await self.action_queue.put({
                "type": "voice_disconnect",
                "payload": {"session": session}
            })
            
        await self._send_notification(session, f"⚫ **{session.display_name}** is now offline.")

    async def _send_notification(self, session: SynchraSession, content: Union[str, discord.Embed]):
        """Queues a notification for a session's text channel."""
        await self.action_queue.put({
            "type": "message",
            "payload": {
                "target": session.text_channel_id,
                "content": content
            }
        })

    @commands.hybrid_group(name="synchra", invoke_without_command=True)
    async def synchra_cmd(self, ctx: commands.Context):
        """
        Synchra Multi-Platform Monitoring.
        """
        if ctx.invoked_subcommand is not None:
            return

        # Determine what to show based on caller permissions
        if await self.bot.is_owner(ctx.author):
            # Owner gets comprehensive account info
            await self._show_owner_info(ctx)
        elif ctx.channel.permissions_for(ctx.author).manage_guild:
            # Admin gets monitored channels list
            await self._show_channels_list(ctx)
        else:
            # Regular users get basic status
            await self._show_basic_status(ctx)
    async def _show_basic_status(self, ctx: commands.Context):
        """Show basic status for regular users."""
        status_icon = "🟢" if self.api.is_connected else "🔴"
        status_text = "Online" if self.api.is_connected else "Offline"
        
        embed = discord.Embed(
            title="🔗 Synchra Bridge Status",
            description=f"Status: {status_icon} `{status_text}`\nMonitored Channels: `{len(self.active_sessions)}`",
            color=discord.Color.green() if self.api.is_connected else discord.Color.red()
        )
        
        await ctx.send(embed=embed)

    async def _show_channels_list(self, ctx: commands.Context):
        """Show monitored channels list for admins."""
        channels = await self.config.monitored_channels()
        if not channels:
            embed = discord.Embed(
                title="📋 Monitored Synchra Channels",
                description="No channels are being monitored.",
                color=discord.Color.orange()
            )
            return await ctx.send(embed=embed)
            
        status_icon = "🟢" if self.api.is_connected else "🔴"
        status_text = "Online" if self.api.is_connected else "Offline"
        live_count = sum(1 for session in self.active_sessions.values() if session.is_live)
        
        embed = discord.Embed(
            title="📋 Monitored Synchra Channels",
            description=f"Bridge Status: {status_icon} `{status_text}`\nTotal Channels: `{len(channels)}`\nLive Channels: `{live_count}`",
            color=discord.Color.blue()
        )
        
        for uuid_str, data in channels.items():
            session = self.active_sessions.get(uuid_str)
            status = "🟢 LIVE" if session and session.is_live else "🔴 Offline"
            platforms = ", ".join(session.platform_names) if session else "Unknown"
            
            # Build detailed channel information
            details = []
            details.append(f"**Status**: {status}")
            details.append(f"**Platforms**: {platforms}")
            details.append(f"**UUID**: `{uuid_str}`")
            
            if session:
                # Discord channel info
                if session.text_channel_id:
                    text_channel = self.bot.get_channel(session.text_channel_id)
                    text_name = text_channel.name if text_channel else f"ID: {session.text_channel_id}"
                    details.append(f"**Text Channel**: #{text_name}")
                
                if session.voice_channel_id:
                    voice_channel = self.bot.get_channel(session.voice_channel_id)
                    voice_name = voice_channel.name if voice_channel else f"ID: {session.voice_channel_id}"
                    details.append(f"**Voice Channel**: 🔊 {voice_name}")
                
                # Feature toggles
                features = []
                if session.chat_enabled: features.append("💬 Chat")
                if session.voice_enabled: features.append("🔊 Voice")
                if features:
                    details.append(f"**Features**: {' '.join(features)}")
                
                # Last live info
                if session.last_live > 0:
                    import datetime
                    last_live_time = datetime.datetime.fromtimestamp(session.last_live)
                    details.append(f"**Last Live**: {last_live_time.strftime('%Y-%m-%d %H:%M')}")
                
                # Current broadcast info if live
                if session.is_live and session.providers:
                    live_provider = next((p for p in session.providers if getattr(p, "is_live", False)), session.providers[0])
                    title = getattr(live_provider, "title", "")
                    game = getattr(live_provider, "game_name", "")
                    if title: details.append(f"**Title**: {title[:50]}{'...' if len(title) > 50 else ''}")
                    if game: details.append(f"**Game**: {game}")
            
            value = "\n".join(details)
            embed.add_field(name=data["display_name"], value=value, inline=False)
        
        await ctx.send(embed=embed)

    async def _show_owner_info(self, ctx: commands.Context):
        """Show comprehensive account info for bot owner."""
        if not self.api.is_ready:
            return await ctx.send(error("Synchra API is not initialized. Check [p]synchra set."))
        
        status_icon = "🟢" if self.api.is_connected else "🔴"
        status_text = "Online" if self.api.is_connected else "Offline"
        channels = await self.config.monitored_channels()
        live_count = sum(1 for session in self.active_sessions.values() if session.is_live)
        
        # Main embed with summary
        embed = discord.Embed(
            title="� Synchra Bridge - Owner Panel",
            description=f"**Bridge Status**: {status_icon} `{status_text}`\n**Total Channels**: `{len(channels)}`\n**Live Channels**: `{live_count}`",
            color=await ctx.embed_color()
        )
        
        # Account Information Section
        user = await self.api.get_user_info()
        if user:
            account_info = (
                f"**Username**: `{user.get('username', 'N/A')}`\n"
                f"**User ID**: `{user.get('id', 'N/A')}`"
            )
            email = user.get('email')
            if email:
                account_info += f"\n**Email**: ||{email}||"
            embed.add_field(name="🔗 Account Verification", value=account_info, inline=False)
        else:
            embed.add_field(name="⚠️ Account Info", value="Could not fetch user info for this Synchra token.", inline=False)
        
        # User Providers Section
        providers = await self.api.get_user_providers()
        if providers:
            provider_list = []
            for p in providers:
                p_id = p.get("id")
                p_type = p.get("provider_type", "Unknown").capitalize()
                p_name = p.get("display_name") or p.get("provider_channel_name") or "Unnamed"
                is_active = str(p_id) == str(self.user_provider_id)
                status_emoji = "✅" if is_active else "🔗"
                provider_list.append(f"{status_emoji} **{p_type}**: {p_name} (`{p_id}`)")
            
            embed.add_field(
                name="👤 Linked Providers", 
                value="\n".join(provider_list), 
                inline=False
            )
        else:
            embed.add_field(name="⚠️ Providers", value="No account providers found for this Synchra token.", inline=False)
        
        # Detailed Channel Information Section
        if channels:
            channel_details = []
            for uuid_str, data in list(channels.items())[:5]:  # Limit to first 5 channels to avoid embed overflow
                session = self.active_sessions.get(uuid_str)
                status = "🟢" if session and session.is_live else "🔴"
                platforms = ", ".join(session.platform_names[:2]) if session else "Unknown"  # Limit platforms display
                
                detail = f"{status} **{data['display_name']}** - {platforms}"
                if session and session.text_channel_id:
                    text_channel = self.bot.get_channel(session.text_channel_id)
                    if text_channel:
                        detail += f" → #{text_channel.name}"
                channel_details.append(detail)
            
            if len(channels) > 5:
                channel_details.append(f"... and {len(channels) - 5} more channels")
            
            embed.add_field(
                name="📋 Channel Overview", 
                value="\n".join(channel_details), 
                inline=False
            )
        
        await ctx.send(embed=embed)

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

        display_name = clean_name(channel.display_name or channel.name)
        
        # Initialize webhook
        webhook_url = await ensure_webhook(text_channel)

        uuid_str = str(channel.id)
        async with self.config.monitored_channels() as channels:
            channels[uuid_str] = {
                "display_name": display_name,
                "text_channel_id": text_channel.id,
                "voice_channel_id": voice_channel.id if voice_channel else None,
                "voice_enabled": True if voice_channel else False,
                "chat_enabled": True,
                "last_live": 0,
                "webhook_url": webhook_url
            }
        
        # Create session
        session = SynchraSession(
            channel_uuid=channel.id,
            display_name=display_name,
            text_channel_id=text_channel.id,
            voice_channel_id=voice_channel.id if voice_channel else None,
            webhook_url=webhook_url
        )
        session.providers = await self.api.get_providers(channel.id)
        self.active_sessions[uuid_str] = session
        
        if self.ws:
            await self.ws.subscribe(session.channel_uuid)

        await ctx.send(success(f"Now monitoring **{channel.display_name}**! UUID: `{uuid_str}`"))

    @synchra_cmd.command(name="stop")
    @checks.admin_or_permissions(manage_guild=True)
    async def stop(self, ctx, channel_id_or_handle: str):
        """Stop monitoring a channel."""
        found_uuid = None
        async with self.config.monitored_channels() as channels:
            for uuid_str, data in channels.items():
                if uuid_str == channel_id_or_handle:
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
                            "display_name": channel.display_name or channel.name,
                            "text_channel_id": data.get("text_channel_id"),
                            "voice_channel_id": data.get("voice_channel_id"),
                            "voice_enabled": data.get("voice_enabled", True),
                            "chat_enabled": data.get("chat_enabled", True),
                            "last_live": data.get("last_live", 0)
                        }
                    
                    # Register in active sessions immediately
                    session = SynchraSession(
                        channel_uuid=channel.id,
                        display_name=channel.display_name or channel.name,
                        text_channel_id=data.get("text_channel_id"),
                        voice_channel_id=data.get("voice_channel_id"),
                    )
                    session.providers = await self.api.get_providers(channel.id)
                    self.active_sessions[uuid_str] = session
                    if self.ws:
                        await self.ws.subscribe(session.channel_uuid)
                    
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
