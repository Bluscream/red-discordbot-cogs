"""ActivisionStatus cog for Red-DiscordBot"""

from contextlib import suppress
from typing import Any, ClassVar, Dict, List, Optional, Set, Tuple
from datetime import datetime, timedelta
from logging import getLogger
from pathlib import Path
import asyncio
import aiohttp
import json

import discord
from discord.ext import tasks
from redbot.core import Config, checks, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import error, info, success, warning, box

from .pcx_lib import *

log = getLogger("red.blu.activisionstatus")


class ActivisionStatus:
    """Class to interact with Activision's status API."""

    API_URL = "https://prod-psapi.infra-ext.activision.com/open/api/apexrest/oshp/landingpage"

    def __init__(self, session: Optional[aiohttp.ClientSession] = None, cache_file: Optional[Path] = None, cache_age: int = 300):
        """Initialize the ActivisionStatus class.
        
        Args:
            session: Optional aiohttp session to use
            cache_file: Optional path to cache file
            cache_age: Cache age in seconds before fetching new data (default: 300 = 5 minutes)
        """
        self.session = session
        self._last_data: Optional[Dict[str, Any]] = None
        self._last_fetch_time: Optional[datetime] = None
        self.cache_file = cache_file
        self.cache_age = cache_age

    async def fetch_status(self, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
        """Fetch the current status from Activision's API.
        
        Args:
            force_refresh: If True, bypass cache and fetch from API
        
        Returns:
            Status data dictionary or None if fetch failed
        """
        # Check cache first if not forcing refresh
        if not force_refresh:
            cached_data = self._load_cache()
            if cached_data:
                cache_time = cached_data.get("_cache_timestamp")
                if cache_time:
                    try:
                        cache_dt = datetime.fromisoformat(cache_time)
                        age = (datetime.utcnow() - cache_dt).total_seconds()
                        if age < self.cache_age:
                            log.debug(f"Using cached data (age: {age:.1f}s)")
                            self._last_data = cached_data.get("data")
                            self._last_fetch_time = cache_dt
                            return self._last_data
                        else:
                            log.debug(f"Cache expired (age: {age:.1f}s, max: {self.cache_age}s)")
                    except Exception as e:
                        log.warning(f"Error parsing cache timestamp: {e}")
        
        # Fetch from API
        if not self.session:
            async with aiohttp.ClientSession() as session:
                data = await self._fetch_with_session(session)
        else:
            data = await self._fetch_with_session(self.session)
        
        # Save to cache if fetch was successful
        if data and self.cache_file:
            self._save_cache(data)
        
        return data

    async def _fetch_with_session(self, session: aiohttp.ClientSession) -> Optional[Dict[str, Any]]:
        """Internal method to fetch status with a session."""
        try:
            async with session.get(self.API_URL, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    self._last_data = data
                    self._last_fetch_time = datetime.utcnow()
                    return data
                else:
                    log.warning(f"Failed to fetch Activision status: HTTP {response.status}")
                    return None
        except asyncio.TimeoutError:
            log.warning("Timeout while fetching Activision status")
            return None
        except aiohttp.ClientError as e:
            log.error(f"Error fetching Activision status: {e}")
            return None
        except Exception as e:
            log.error(f"Unexpected error fetching Activision status: {e}")
            return None

    def _save_cache(self, data: Dict[str, Any]) -> None:
        """Save data to cache file."""
        if not self.cache_file:
            return
        
        try:
            cache_data = {
                "_cache_timestamp": datetime.utcnow().isoformat(),
                "data": data
            }
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            with self.cache_file.open("w", encoding="utf-8") as f:
                json.dump(cache_data, f, indent=2)
            log.debug(f"Saved cache to {self.cache_file}")
        except Exception as e:
            log.warning(f"Failed to save cache: {e}")

    def _load_cache(self) -> Optional[Dict[str, Any]]:
        """Load data from cache file."""
        if not self.cache_file or not self.cache_file.exists():
            return None
        
        try:
            with self.cache_file.open("r", encoding="utf-8") as f:
                cache_data = json.load(f)
                log.debug(f"Loaded cache from {self.cache_file}")
                return cache_data
        except json.JSONDecodeError as e:
            log.warning(f"Invalid cache file format: {e}")
            return None
        except Exception as e:
            log.warning(f"Failed to load cache: {e}")
            return None

    def get_server_statuses(self, data: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Get the list of server statuses (games with issues)."""
        if data is None:
            data = self._last_data
        if not data:
            return []
        return data.get("serverStatuses", [])

    def get_platforms(self, data: Optional[Dict[str, Any]] = None) -> List[str]:
        """Get the list of available platforms."""
        if data is None:
            data = self._last_data
        if not data:
            return []
        return data.get("platformsRO", [])

    def get_red_alerts(self, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Get active red alerts."""
        if data is None:
            data = self._last_data
        if not data:
            return {}
        return data.get("redAlerts", {})

    def get_recently_resolved(self, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Get recently resolved incidents."""
        if data is None:
            data = self._last_data
        if not data:
            return {}
        return data.get("recentlyResolved", {})

    def get_updated_time(self, data: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Get the timestamp of when the data was last updated."""
        if data is None:
            data = self._last_data
        if not data:
            return None
        return data.get("updatedTime")

    def is_game_online(self, game_title: str, platform: str, data: Optional[Dict[str, Any]] = None) -> bool:
        """Check if a specific game/platform combination is online."""
        server_statuses = self.get_server_statuses(data)
        # If game/platform is NOT in serverStatuses, it's online
        has_issue = any(
            status.get("gameTitle") == game_title and status.get("platform") == platform
            for status in server_statuses
        )
        return not has_issue

    def get_games_with_issues(self, data: Optional[Dict[str, Any]] = None) -> Set[Tuple[str, str]]:
        """Get a set of (game_title, platform) tuples for games with issues."""
        server_statuses = self.get_server_statuses(data)
        return {
            (status.get("gameTitle", ""), status.get("platform", ""))
            for status in server_statuses
            if status.get("gameTitle") and status.get("platform")
        }

    def get_all_games(self, data: Optional[Dict[str, Any]] = None) -> Set[str]:
        """Get all unique game titles from server statuses."""
        server_statuses = self.get_server_statuses(data)
        return {status.get("gameTitle", "") for status in server_statuses if status.get("gameTitle")}


class ActivisionStatusCog(commands.Cog):
    """Monitor Activision online services status and post updates to channels."""

    __author__ = "Bluscream"
    __version__ = "1.0.0"

    default_global_settings: ClassVar[Dict[str, Any]] = {
        "schema_version": 1,
        "check_interval": 300,  # 5 minutes default
        "update_bot_status": False,
        "cache_age": 300,  # Cache age in seconds (5 minutes default)
    }

    default_guild_settings: ClassVar[Dict[str, Any]] = {
        "channels": [],  # List of channel IDs to post updates to
    }

    def __init__(self, bot: Red) -> None:
        """Set up the cog."""
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=1884366864, force_registration=True
        )
        self.config.register_global(**self.default_global_settings)
        self.config.register_guild(**self.default_guild_settings)
        
        # Set up cache file path
        cog_path = Path(__file__).parent
        self.cache_file = cog_path / "status_cache.json"
        
        self.status_api = None  # Will be initialized in initialize()
        self._last_known_statuses: Set[Tuple[str, str]] = set()
        self._session: Optional[aiohttp.ClientSession] = None
        self._task_started = False

    #
    # Red methods
    #

    def format_help_for_context(self, ctx: commands.Context) -> str:
        """Show version in help."""
        pre_processed = super().format_help_for_context(ctx)
        return f"{pre_processed}\n\nCog Version: {self.__version__}"

    async def red_delete_data_for_user(self, *, _requester: str, _user_id: int) -> None:
        return

    #
    # Initialization methods
    #

    async def initialize(self) -> None:
        """Perform setup actions before loading cog."""
        await self._migrate_config()
        self._session = aiohttp.ClientSession()
        
        # Initialize status API with cache
        cache_age = await self.config.cache_age()
        self.status_api = ActivisionStatus(
            session=self._session,
            cache_file=self.cache_file,
            cache_age=cache_age
        )
        
        # Try to load from cache on startup
        cached_data = self.status_api._load_cache()
        if cached_data:
            cache_time = cached_data.get("_cache_timestamp")
            if cache_time:
                try:
                    cache_dt = datetime.fromisoformat(cache_time)
                    self.status_api._last_data = cached_data.get("data")
                    self.status_api._last_fetch_time = cache_dt
                    # Initialize last_known_statuses from cache
                    if self.status_api._last_data:
                        self._last_known_statuses = self.status_api.get_games_with_issues(self.status_api._last_data)
                    log.info(f"Loaded status from cache (age: {(datetime.utcnow() - cache_dt).total_seconds():.1f}s)")
                except Exception as e:
                    log.warning(f"Error loading cache on startup: {e}")
        
        # Set initial interval from config
        interval = await self.config.check_interval()
        self.status_check_loop.change_interval(seconds=interval)
        # Start the background task
        if not self._task_started:
            self.status_check_loop.start()
            self._task_started = True

    async def _migrate_config(self) -> None:
        """Perform some configuration migrations."""
        schema_version = await self.config.schema_version()
        
        if schema_version < 1:
            await self.config.schema_version.set(1)
            log.info("Migrated ActivisionStatus config to schema version 1")

    def cog_unload(self) -> None:
        """Clean up when cog is unloaded."""
        self.status_check_loop.cancel()
        if self._session:
            asyncio.create_task(self._session.close())

    #
    # Background tasks
    #

    @tasks.loop(seconds=300)  # Default 5 minutes, will be updated from config
    async def status_check_loop(self) -> None:
        """Background task to check status periodically."""
        try:
            data = await self.status_api.fetch_status()
            if not data:
                return

            current_statuses = self.status_api.get_games_with_issues(data)
            
            # Check for new issues (games that went offline)
            new_issues = current_statuses - self._last_known_statuses
            # Check for resolved issues (games that came back online)
            resolved_issues = self._last_known_statuses - current_statuses

            if new_issues or resolved_issues:
                await self._post_status_updates(new_issues, resolved_issues, data)
                await self._update_bot_status(data)

            self._last_known_statuses = current_statuses

        except Exception as e:
            log.error(f"Error in status check loop: {e}", exc_info=True)

    @status_check_loop.before_loop
    async def before_status_check_loop(self) -> None:
        """Wait until bot is ready before starting the loop."""
        await self.bot.wait_until_ready()
        # Initial fetch to populate last_known_statuses
        data = await self.status_api.fetch_status()
        if data:
            self._last_known_statuses = self.status_api.get_games_with_issues(data)

    #
    # Internal methods
    #

    async def _post_status_updates(
        self,
        new_issues: Set[Tuple[str, str]],
        resolved_issues: Set[Tuple[str, str]],
        data: Dict[str, Any]
    ) -> None:
        """Post status updates to configured channels."""
        if not new_issues and not resolved_issues:
            return

        for guild in self.bot.guilds:
            channels = await self.config.guild(guild).channels()
            if not channels:
                continue

            embed = await self._create_status_embed(new_issues, resolved_issues, data)

            for channel_id in channels:
                channel = guild.get_channel(channel_id)
                if channel and channel.permissions_for(guild.me).send_messages:
                    try:
                        await channel.send(embed=embed)
                    except discord.HTTPException as e:
                        log.error(f"Failed to send status update to channel {channel_id}: {e}")

    async def _create_status_embed(
        self,
        new_issues: Set[Tuple[str, str]],
        resolved_issues: Set[Tuple[str, str]],
        data: Dict[str, Any]
    ) -> discord.Embed:
        """Create an embed for status updates."""
        embed = discord.Embed(
            title="Activision Service Status Update",
            color=discord.Color.orange() if new_issues else discord.Color.green(),
            timestamp=datetime.utcnow()
        )

        updated_time = self.status_api.get_updated_time(data)
        if updated_time:
            try:
                dt = datetime.fromisoformat(updated_time.replace("Z", "+00:00"))
                embed.set_footer(text=f"Last updated: {dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
            except Exception:
                pass

        if new_issues:
            issues_text = "\n".join(
                f"• **{game}** ({platform})" for game, platform in sorted(new_issues)
            )
            if len(issues_text) > 1024:
                issues_text = issues_text[:1021] + "..."
            embed.add_field(
                name="⚠️ New Issues Detected",
                value=issues_text or "No details available",
                inline=False
            )

        if resolved_issues:
            resolved_text = "\n".join(
                f"• **{game}** ({platform})" for game, platform in sorted(resolved_issues)
            )
            if len(resolved_text) > 1024:
                resolved_text = resolved_text[:1021] + "..."
            embed.add_field(
                name="✅ Issues Resolved",
                value=resolved_text or "No details available",
                inline=False
            )

        if not new_issues and not resolved_issues:
            embed.description = "No status changes detected."

        return embed

    async def _update_bot_status(self, data: Dict[str, Any]) -> None:
        """Update bot's custom status if enabled."""
        update_status = await self.config.update_bot_status()
        if not update_status:
            return

        issues = self.status_api.get_games_with_issues(data)
        if issues:
            # Set status to show there are issues
            status_text = f"{len(issues)} game(s) with issues"
            activity = discord.Activity(
                type=discord.ActivityType.watching,
                name=status_text
            )
        else:
            # Set status to show all clear
            activity = discord.Activity(
                type=discord.ActivityType.watching,
                name="Activision Services - All Online"
            )

        try:
            await self.bot.change_presence(activity=activity)
        except Exception as e:
            log.error(f"Failed to update bot status: {e}")

    #
    # Commands
    #

    @commands.group(name="status")
    async def status_group(self, ctx: commands.Context) -> None:
        """Status monitoring commands."""
        pass

    @status_group.group(name="activision", aliases=["act", "cod"])
    async def activision_group(self, ctx: commands.Context) -> None:
        """Activision status monitoring commands."""
        pass

    @activision_group.command(name="check")
    async def check_status(self, ctx: commands.Context, force: bool = False) -> None:
        """Manually check the current Activision service status.
        
        Args:
            force: If True, bypasses cache and fetches fresh data from API
        """
        async with ctx.typing():
            data = await self.status_api.fetch_status(force_refresh=force)
            if not data:
                await reply(ctx, error("Failed to fetch status from Activision API."))
                return

            issues = self.status_api.get_games_with_issues(data)
            server_statuses = self.status_api.get_server_statuses(data)
            updated_time = self.status_api.get_updated_time(data)

            embed = discord.Embed(
                title="Activision Service Status",
                color=discord.Color.red() if issues else discord.Color.green(),
                timestamp=datetime.utcnow()
            )

            # Add cache info to footer
            cache_info = []
            if self.status_api._last_fetch_time:
                age = (datetime.utcnow() - self.status_api._last_fetch_time).total_seconds()
                cache_info.append(f"Cache age: {age:.0f}s")
            if force:
                cache_info.append("(Force refresh)")
            
            if updated_time:
                try:
                    dt = datetime.fromisoformat(updated_time.replace("Z", "+00:00"))
                    footer_text = f"Last updated: {dt.strftime('%Y-%m-%d %H:%M:%S UTC')}"
                    if cache_info:
                        footer_text += f" | {' | '.join(cache_info)}"
                    embed.set_footer(text=footer_text)
                except Exception:
                    if cache_info:
                        embed.set_footer(text=" | ".join(cache_info))

            if issues:
                issues_list = "\n".join(
                    f"• **{game}** ({platform})" for game, platform in sorted(issues)
                )
                if len(issues_list) > 1024:
                    issues_list = issues_list[:1021] + "..."
                embed.add_field(
                    name=f"⚠️ Games with Issues ({len(issues)})",
                    value=issues_list or "No details available",
                    inline=False
                )
            else:
                embed.description = "✅ All services are online!"

            if server_statuses:
                embed.add_field(
                    name="Total Issues",
                    value=str(len(server_statuses)),
                    inline=True
                )

            await reply(ctx, embed=embed)

    @activision_group.command(name="addchannel")
    @checks.admin_or_permissions(manage_guild=True)
    async def add_channel(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None) -> None:
        """Add a channel to receive status updates.
        
        If no channel is specified, uses the current channel.
        """
        if not ctx.guild:
            await reply(ctx, error("This command can only be used in a server."))
            return

        target_channel = channel or ctx.channel
        if not isinstance(target_channel, discord.TextChannel):
            await reply(ctx, error("Please specify a valid text channel."))
            return

        async with self.config.guild(ctx.guild).channels() as channels:
            if target_channel.id not in channels:
                channels.append(target_channel.id)
                await reply(ctx, success(f"Added {target_channel.mention} to receive status updates."))
            else:
                await reply(ctx, info(f"{target_channel.mention} is already receiving status updates."))

    @activision_group.command(name="removechannel")
    @checks.admin_or_permissions(manage_guild=True)
    async def remove_channel(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None) -> None:
        """Remove a channel from receiving status updates.
        
        If no channel is specified, uses the current channel.
        """
        if not ctx.guild:
            await reply(ctx, error("This command can only be used in a server."))
            return

        target_channel = channel or ctx.channel
        if not isinstance(target_channel, discord.TextChannel):
            await reply(ctx, error("Please specify a valid text channel."))
            return

        async with self.config.guild(ctx.guild).channels() as channels:
            if target_channel.id in channels:
                channels.remove(target_channel.id)
                await reply(ctx, success(f"Removed {target_channel.mention} from status updates."))
            else:
                await reply(ctx, info(f"{target_channel.mention} is not receiving status updates."))

    @activision_group.command(name="listchannels")
    async def list_channels(self, ctx: commands.Context) -> None:
        """List all channels configured to receive status updates."""
        if not ctx.guild:
            await reply(ctx, error("This command can only be used in a server."))
            return

        channels = await self.config.guild(ctx.guild).channels()
        if not channels:
            await reply(ctx, info("No channels are configured to receive status updates."))
            return

        channel_mentions = []
        for channel_id in channels:
            channel = ctx.guild.get_channel(channel_id)
            if channel:
                channel_mentions.append(f"• {channel.mention} ({channel.name})")
            else:
                channel_mentions.append(f"• Unknown channel (ID: {channel_id})")

        embed = discord.Embed(
            title="Status Update Channels",
            description="\n".join(channel_mentions),
            color=discord.Color.blue()
        )
        await reply(ctx, embed=embed)

    @activision_group.command(name="interval")
    async def interval_command(self, ctx: commands.Context, seconds: Optional[int] = None) -> None:
        """Get or set the check interval in seconds (minimum 60).
        
        If no value is provided, shows the current interval.
        Only admins can set the interval.
        Example: `[p]status activision interval 300` (5 minutes)
        """
        if seconds is None:
            interval = await self.config.check_interval()
            await reply(ctx, info(f"Current check interval: {interval} seconds ({interval // 60} minutes)."))
            return

        # Check permissions for setting
        if not ctx.author.guild_permissions.administrator:
            await reply(ctx, error("You need administrator permissions to set the interval."))
            return

        if seconds < 60:
            await reply(ctx, error("Interval must be at least 60 seconds."))
            return

        await self.config.check_interval.set(seconds)
        # Update the loop interval
        self.status_check_loop.change_interval(seconds=seconds)
        await reply(ctx, success(f"Check interval set to {seconds} seconds ({seconds // 60} minutes)."))

    @activision_group.command(name="cacheage")
    async def cache_age_command(self, ctx: commands.Context, seconds: Optional[int] = None) -> None:
        """Get or set the cache age in seconds (minimum 60).
        
        Cache age determines how long cached data is used before fetching new data from the API.
        If no value is provided, shows the current cache age.
        Only admins can set the cache age.
        Example: `[p]status activision cacheage 600` (10 minutes)
        """
        if seconds is None:
            cache_age = await self.config.cache_age()
            await reply(ctx, info(f"Current cache age: {cache_age} seconds ({cache_age // 60} minutes)."))
            return

        # Check permissions for setting
        if not ctx.author.guild_permissions.administrator:
            await reply(ctx, error("You need administrator permissions to set the cache age."))
            return

        if seconds < 60:
            await reply(ctx, error("Cache age must be at least 60 seconds."))
            return

        await self.config.cache_age.set(seconds)
        # Update the status API cache age
        self.status_api.cache_age = seconds
        await reply(ctx, success(f"Cache age set to {seconds} seconds ({seconds // 60} minutes)."))

    @activision_group.command(name="botstatus")
    @checks.admin()
    async def toggle_bot_status(self, ctx: commands.Context, enabled: Optional[bool] = None) -> None:
        """Toggle or set whether the bot's status should be updated with Activision status.
        
        If no value is provided, toggles the current setting.
        """
        current = await self.config.update_bot_status()
        if enabled is None:
            enabled = not current
        else:
            enabled = bool(enabled)

        await self.config.update_bot_status.set(enabled)
        status_text = "enabled" if enabled else "disabled"
        await reply(ctx, success(f"Bot status updates are now {status_text}."))

        # Immediately update status if enabled
        if enabled:
            data = await self.status_api.fetch_status()
            if data:
                await self._update_bot_status(data)
