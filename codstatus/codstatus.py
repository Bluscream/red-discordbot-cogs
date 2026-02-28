"""ActivisionStatus cog for Red-DiscordBot"""

from contextlib import suppress
from typing import Any, ClassVar, Dict, List, Optional, Set, Tuple
from datetime import datetime
from logging import getLogger
from pathlib import Path
import asyncio
import aiohttp

import discord
from discord.ext import tasks
from redbot.core import Config, checks, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import error, info, success, warning, box

from .pcx_lib import *
from .activision import ActivisionAPI
from .regex_utils import RegexParser

log = getLogger("red.blu.activisionstatus")


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
        "channels": {},  # Dict mapping channel_id to {"filters": [regex_patterns]}
    }

    def __init__(self, bot: Red) -> None:
        """Set up the cog."""
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=1884366861, force_registration=True
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
        self.status_api = ActivisionAPI(
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
        
        if schema_version < 2:
            # Initialize channel_filters for all existing guilds
            for guild in self.bot.guilds:
                async with self.config.guild(guild).channel_filters() as filters:
                    # Ensure it's initialized as empty dict if not present
                    if not isinstance(filters, dict):
                        filters = {}
            await self.config.schema_version.set(2)
            log.info("Migrated ActivisionStatus config to schema version 2 (added channel_filters)")
        
        if schema_version < 3:
            # Migrate from separate channels list and channel_filters dict to unified channels dict
            for guild in self.bot.guilds:
                old_channels = await self.config.guild(guild).channels()
                
                # Check if old_channels is a list (old format)
                if isinstance(old_channels, list):
                    # Try to get old filters, but handle case where it doesn't exist
                    try:
                        old_filters = await self.config.guild(guild).channel_filters()
                    except Exception:
                        old_filters = {}
                    
                    new_channels = {}
                    for channel_id in old_channels:
                        channel_key = str(channel_id)
                        filters = old_filters.get(channel_key, []) if isinstance(old_filters, dict) else []
                        new_channels[channel_key] = {"filters": filters}
                    
                    await self.config.guild(guild).channels.set(new_channels)
                    log.info(f"Migrated guild {guild.id} to schema version 3 (unified channels dict)")
            
            await self.config.schema_version.set(3)
            log.info("Migrated ActivisionStatus config to schema version 3 (unified channels dict)")

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

    def _filter_issues_by_games(
        self, issues: Set[Tuple[str, str]], filter_patterns: List[str]
    ) -> Set[Tuple[str, str]]:
        """Filter issues to only include games whose title matches the provided regex patterns.
        
        Args:
            issues: Set of (game_title, platform) tuples
            filter_patterns: List of regex patterns to match against game titles (may include /flags)
        
        Returns:
            Filtered set of issues
        """
        if not filter_patterns:
            return issues  # Empty filter = all games
        
        # Compile regex patterns with parsed flags
        compiled_patterns = []
        for pattern in filter_patterns:
            is_valid, error_msg = RegexParser.validate_pattern(pattern)
            if is_valid:
                compiled_patterns.append(RegexParser.compile_pattern(pattern))
            else:
                log.warning(f"Invalid regex pattern '{pattern}': {error_msg}")
        
        if not compiled_patterns:
            # All patterns were invalid, return empty set
            return set()
        
        # Match game titles against patterns
        filtered = set()
        for game_title, platform in issues:
            for pattern in compiled_patterns:
                if pattern.search(game_title):
                    filtered.add((game_title, platform))
                    break  # Match found, no need to check other patterns
        
        return filtered

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

            # channels is now a dict: {channel_id: {"filters": [...]}}
            for channel_key, channel_config in channels.items():
                try:
                    channel_id = int(channel_key)
                except (ValueError, TypeError):
                    log.warning(f"Invalid channel ID in config: {channel_key}")
                    continue
                
                channel = guild.get_channel(channel_id)
                if not channel or not channel.permissions_for(guild.me).send_messages:
                    continue

                # Get filter list for this channel (empty list = all games)
                filter_list = channel_config.get("filters", [])
                
                # Filter issues for this channel
                filtered_new = self._filter_issues_by_games(new_issues, filter_list)
                filtered_resolved = self._filter_issues_by_games(resolved_issues, filter_list)

                # Only post if there are filtered issues
                if filtered_new or filtered_resolved:
                    embed = await self._create_status_embed(filtered_new, filtered_resolved, data)
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
            channel_key = str(target_channel.id)
            if channel_key not in channels:
                channels[channel_key] = {"filters": []}
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
            channel_key = str(target_channel.id)
            if channel_key in channels:
                del channels[channel_key]
                await reply(ctx, success(f"Removed {target_channel.mention} from status updates."))
            else:
                await reply(ctx, info(f"{target_channel.mention} is not receiving status updates."))

    @activision_group.group(name="channel")
    async def channel_group(self, ctx: commands.Context) -> None:
        """Channel management commands."""
        pass

    @channel_group.command(name="list")
    async def list_channels(self, ctx: commands.Context) -> None:
        """List all channels configured to receive status updates.
        
        In a server: Shows channels for the current server.
        In DMs: Shows channels for all servers (bot owner only).
        """
        if ctx.guild:
            # In a server - show only current server
            channels = await self.config.guild(ctx.guild).channels()
            if not channels:
                await reply(ctx, info("No channels are configured to receive status updates in this server."))
                return

            channel_mentions = []
            for channel_key in channels.keys():
                try:
                    channel_id = int(channel_key)
                except (ValueError, TypeError):
                    continue
                channel = ctx.guild.get_channel(channel_id)
                if channel:
                    channel_mentions.append(f"• {channel.mention} ({channel.name})")
                else:
                    channel_mentions.append(f"• Unknown channel (ID: {channel_key})")

            embed = discord.Embed(
                title=f"Status Update Channels - {ctx.guild.name}",
                description="\n".join(channel_mentions) if channel_mentions else "No channels configured.",
                color=discord.Color.blue()
            )
            await reply(ctx, embed=embed)
        else:
            # In DMs - show all servers (owner only)
            if not await self.bot.is_owner(ctx.author):
                await reply(ctx, error("This command can only be used by the bot owner in DMs."))
                return

            embeds = []
            for guild in self.bot.guilds:
                channels = await self.config.guild(guild).channels()
                if not channels:
                    continue

                channel_mentions = []
                for channel_key in channels.keys():
                    try:
                        channel_id = int(channel_key)
                    except (ValueError, TypeError):
                        continue
                    channel = guild.get_channel(channel_id)
                    if channel:
                        channel_mentions.append(f"• {channel.mention} ({channel.name})")
                    else:
                        channel_mentions.append(f"• Unknown channel (ID: {channel_key})")

                if channel_mentions:
                    embed = discord.Embed(
                        title=f"Status Update Channels - {guild.name}",
                        description="\n".join(channel_mentions),
                        color=discord.Color.blue()
                    )
                    embeds.append(embed)

            if not embeds:
                await reply(ctx, info("No channels are configured to receive status updates in any server."))
                return

            # Send all embeds (split if too many)
            for embed in embeds:
                await reply(ctx, embed=embed)

    @channel_group.group(name="filter")
    async def filter_group(self, ctx: commands.Context) -> None:
        """Manage game filters for channels."""
        pass

    @filter_group.command(name="add")
    @checks.admin_or_permissions(manage_guild=True)
    async def filter_add(self, ctx: commands.Context, pattern: str, channel: Optional[discord.TextChannel] = None) -> None:
        """Add a regex pattern to the channel's filter list.
        
        Only games matching patterns in the filter list will trigger status updates for this channel.
        If no channel is specified, uses the current channel.
        
        Patterns are case-sensitive by default. Use /i flag for case-insensitive matching.
        Example: `.*call of duty.*/i` for case-insensitive matching.
        
        Args:
            pattern: Regex pattern to match game titles (case-sensitive by default, use /i flag for case-insensitive)
            channel: Optional channel to configure (defaults to current channel)
        """
        if not ctx.guild:
            await reply(ctx, error("This command can only be used in a server."))
            return

        target_channel = channel or ctx.channel
        if not isinstance(target_channel, discord.TextChannel):
            await reply(ctx, error("Please specify a valid text channel."))
            return

        # Validate regex pattern (parse flags if present)
        is_valid, error_msg = RegexParser.validate_pattern(pattern)
        if not is_valid:
            await reply(ctx, error(f"Invalid regex pattern: {error_msg}"))
            return

        async with self.config.guild(ctx.guild).channels() as channels:
            channel_key = str(target_channel.id)
            if channel_key not in channels:
                await reply(ctx, error(f"{target_channel.mention} is not configured to receive status updates. Add it first with `{ctx.prefix}status activision addchannel`."))
                return
            
            # Ensure filters key exists
            if "filters" not in channels[channel_key]:
                channels[channel_key]["filters"] = []
            
            if pattern not in channels[channel_key]["filters"]:
                channels[channel_key]["filters"].append(pattern)
                await reply(ctx, success(f"Added pattern `{pattern}` to {target_channel.mention}'s filter list."))
            else:
                await reply(ctx, info(f"Pattern `{pattern}` is already in {target_channel.mention}'s filter list."))

    @filter_group.command(name="remove")
    @checks.admin_or_permissions(manage_guild=True)
    async def filter_remove(self, ctx: commands.Context, pattern: str, channel: Optional[discord.TextChannel] = None) -> None:
        """Remove a regex pattern from the channel's filter list.
        
        If no channel is specified, uses the current channel.
        
        Args:
            pattern: Regex pattern to remove from the filter
            channel: Optional channel to configure (defaults to current channel)
        """
        if not ctx.guild:
            await reply(ctx, error("This command can only be used in a server."))
            return

        target_channel = channel or ctx.channel
        if not isinstance(target_channel, discord.TextChannel):
            await reply(ctx, error("Please specify a valid text channel."))
            return

        async with self.config.guild(ctx.guild).channels() as channels:
            channel_key = str(target_channel.id)
            if channel_key in channels and "filters" in channels[channel_key] and pattern in channels[channel_key]["filters"]:
                channels[channel_key]["filters"].remove(pattern)
                # Keep filters key even if empty (for consistency)
                await reply(ctx, success(f"Removed pattern `{pattern}` from {target_channel.mention}'s filter list."))
            else:
                await reply(ctx, info(f"Pattern `{pattern}` is not in {target_channel.mention}'s filter list."))

    @filter_group.command(name="list")
    async def filter_list(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None) -> None:
        """List all regex patterns in the channel's filter list.
        
        If no channel is specified, uses the current channel.
        Empty filter list means all games are shown.
        
        Args:
            channel: Optional channel to check (defaults to current channel)
        """
        if not ctx.guild:
            await reply(ctx, error("This command can only be used in a server."))
            return

        target_channel = channel or ctx.channel
        if not isinstance(target_channel, discord.TextChannel):
            await reply(ctx, error("Please specify a valid text channel."))
            return

        channels = await self.config.guild(ctx.guild).channels()
        channel_key = str(target_channel.id)
        channel_config = channels.get(channel_key, {})
        filter_list = channel_config.get("filters", [])

        if not filter_list:
            await reply(ctx, info(f"{target_channel.mention} has no filter configured. All games will trigger status updates."))
        else:
            patterns_text = "\n".join(f"• `{pattern}`" for pattern in sorted(filter_list))
            embed = discord.Embed(
                title=f"Game Filter - {target_channel.name}",
                description=patterns_text,
                color=discord.Color.blue()
            )
            embed.set_footer(text="Only games matching these patterns will trigger status updates for this channel.")
            await reply(ctx, embed=embed)

    @filter_group.command(name="clear")
    @checks.admin_or_permissions(manage_guild=True)
    async def filter_clear(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None) -> None:
        """Clear the channel's filter list (show all games).
        
        If no channel is specified, uses the current channel.
        
        Args:
            channel: Optional channel to clear (defaults to current channel)
        """
        if not ctx.guild:
            await reply(ctx, error("This command can only be used in a server."))
            return

        target_channel = channel or ctx.channel
        if not isinstance(target_channel, discord.TextChannel):
            await reply(ctx, error("Please specify a valid text channel."))
            return

        async with self.config.guild(ctx.guild).channels() as channels:
            channel_key = str(target_channel.id)
            if channel_key in channels:
                channels[channel_key]["filters"] = []
                await reply(ctx, success(f"Cleared {target_channel.mention}'s filter list. All games will now trigger status updates."))
            else:
                await reply(ctx, info(f"{target_channel.mention} is not configured to receive status updates."))

    @activision_group.command(name="games")
    async def list_games(self, ctx: commands.Context) -> None:
        """List all available game titles from the current API data.
        
        Use these exact game titles when adding filters.
        """
        async with ctx.typing():
            data = await self.status_api.fetch_status()
            if not data:
                await reply(ctx, error("Failed to fetch status from Activision API."))
                return

            # Get all unique game titles from current issues and historical data
            current_games = self.status_api.get_all_games(data)
            server_statuses = self.status_api.get_server_statuses(data)
            
            # Also check recently resolved for more game titles
            recently_resolved = self.status_api.get_recently_resolved(data)
            all_games = set(current_games)
            
            # Extract games from server statuses
            for status in server_statuses:
                if status.get("gameTitle"):
                    all_games.add(status["gameTitle"])

            if not all_games:
                await reply(ctx, info("No games found in current API data. This might mean all services are online."))
                return

            games_list = sorted(all_games)
            games_text = "\n".join(f"• **{game}**" for game in games_list)
            
            # Split into multiple embeds if too long
            if len(games_text) > 4096:
                # Split into chunks
                chunks = []
                current_chunk = []
                current_length = 0
                
                for game in games_list:
                    game_line = f"• **{game}**\n"
                    if current_length + len(game_line) > 1024:
                        chunks.append("\n".join(current_chunk))
                        current_chunk = [game_line.strip()]
                        current_length = len(game_line)
                    else:
                        current_chunk.append(game_line.strip())
                        current_length += len(game_line)
                
                if current_chunk:
                    chunks.append("\n".join(current_chunk))
                
                for i, chunk in enumerate(chunks):
                    embed = discord.Embed(
                        title=f"Available Games ({i+1}/{len(chunks)})",
                        description=chunk,
                        color=discord.Color.blue()
                    )
                    embed.set_footer(text="Use these exact titles when adding filters.")
                    await reply(ctx, embed=embed)
            else:
                embed = discord.Embed(
                    title="Available Games",
                    description=games_text,
                    color=discord.Color.blue()
                )
                embed.set_footer(text=f"Total: {len(games_list)} games | Use these exact titles when adding filters.")
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
        self.status_api.status_api.cache_age = seconds
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

    @activision_group.command(name="bancheck", aliases=["checkban"])
    async def ban_check(self, ctx: commands.Context, account_id: str) -> None:
        """Check ban status for an Activision account.
        
        Args:
            account_id: The Activision account ID to check
        """
        async with ctx.typing():
            try:
                ban_data = await self.status_api.check_ban_status(account_id)
                
                if not ban_data:
                    await reply(ctx, error("Failed to check ban status. The service might be temporarily unavailable."))
                    return
                
                # Create embed for ban status
                embed = discord.Embed(
                    title=f"Ban Status Check - {account_id}",
                    color=discord.Color.orange(),
                    timestamp=datetime.utcnow()
                )
                
                # Parse the ban data response
                if isinstance(ban_data, dict):
                    # Check if there's ban information
                    if ban_data.get("banned") is True:
                        embed.color = discord.Color.red()
                        embed.description = "🚫 **Account is BANNED**"
                        
                        # Add ban details if available
                        ban_reason = ban_data.get("reason", "No reason provided")
                        ban_date = ban_data.get("banDate", "Unknown")
                        ban_duration = ban_data.get("duration", "Unknown")
                        
                        embed.add_field(name="Reason", value=ban_reason, inline=False)
                        embed.add_field(name="Ban Date", value=ban_date, inline=True)
                        embed.add_field(name="Duration", value=ban_duration, inline=True)
                        
                        # Add appeal information if available
                        if ban_data.get("canAppeal"):
                            embed.add_field(
                                name="Appeal", 
                                value="You can appeal this ban at: https://support.activision.com/ban-appeal",
                                inline=False
                            )
                        else:
                            embed.add_field(name="Appeal", value="This ban cannot be appealed.", inline=False)
                            
                    elif ban_data.get("banned") is False:
                        embed.color = discord.Color.green()
                        embed.description = "✅ **Account is NOT BANNED**"
                        embed.add_field(name="Status", value="Account is in good standing", inline=False)
                        
                    else:
                        # Ambiguous response, show what we got
                        embed.color = discord.Color.yellow()
                        embed.description = "⚠️ **Unable to determine ban status**"
                        
                        # Show available data
                        if "message" in ban_data:
                            embed.add_field(name="Message", value=ban_data["message"], inline=False)
                        else:
                            embed.add_field(
                                name="Response", 
                                value=f"```json\n{json.dumps(ban_data, indent=2)[:1000]}```",
                                inline=False
                            )
                else:
                    # Non-dict response, show as is
                    embed.color = discord.Color.yellow()
                    embed.description = "⚠️ **Unexpected response format**"
                    embed.add_field(
                        name="Response", 
                        value=f"```json\n{json.dumps(ban_data, indent=2)[:1000]}```",
                        inline=False
                    )
                
                embed.set_footer(text="Ban status information from Activision Support")
                await reply(ctx, embed=embed)
                
            except Exception as e:
                log.error(f"Error in ban check command: {e}", exc_info=True)
                await reply(ctx, error(f"An error occurred while checking ban status: {str(e)}"))
