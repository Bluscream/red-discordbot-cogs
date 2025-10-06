"""GameChannel cog for Red-DiscordBot"""

from contextlib import suppress
from typing import Any, ClassVar, List, Dict, Optional, Union
from datetime import date, datetime, timedelta
from logging import getLogger
from random import randint, choice
from json import dumps, loads
import asyncio
import aiohttp

import discord, pytz, os
from discord.ext import tasks # commands
from redbot.core import Config, checks, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import error, info, success, warning

from .pcx_lib import *

log = getLogger("red.blu.gamechannel")

from .strings import Strings
lang = Strings('de')

detectable_schema_url = "https://bluscream.github.io/discord-games/detectable.schema.json"
detectable_api_url = "https://discord.com/api/v9/applications/detectable"

class GameChannel(commands.Cog):
    """
    """

    __author__ = "Bluscream"
    __version__ = "1.0.0"

    default_global_settings: ClassVar[dict[str, Union[int, dict]]] = {
        "schema_version": 1,
        "backup_data": {}
    }

    default_guild_settings: ClassVar[dict[str, dict[int, List[int]]]] = {
        "channels": {}
    }

    def __init__(self, bot: Red) -> None:
        """Set up the cog."""
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=1884366863, force_registration=True
        )
        self.config.register_global(**self.default_global_settings)
        self.config.register_guild(**self.default_guild_settings)
        self.bucket_member_join_cache = commands.CooldownMapping.from_cooldown(
            1, 300, lambda member: member
        )
        self._detectable_games_cache: Optional[Dict[str, Dict]] = None
        self._cache_expiry: Optional[datetime] = None

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

    async def _migrate_config(self) -> None:
        """Perform some configuration migrations."""
        schema_version = await self.config.schema_version()
        
        if schema_version < 1:
            await self._migrate_to_v1()
            await self.config.schema_version.set(1)
            log.info("Migrated GameChannel config to schema version 1")

    async def _migrate_to_v1(self) -> None:
        """Migrate from single game IDs to multiple game IDs per channel."""
        log.info("Starting migration to schema version 1 (single game -> multiple games)")
        
        migrated_guilds = 0
        migrated_channels = 0
        backup_data = {}
        
        for guild in self.bot.guilds:
            try:
                guild_config = self.config.guild(guild)
                channels = await guild_config.channels()
                
                if not channels:
                    continue
                
                # Create backup of original data
                backup_data[str(guild.id)] = dict(channels)
                
                # Check if this is old format (single int values) or new format (list values)
                needs_migration = False
                new_channels = {}
                
                for channel_id, value in channels.items():
                    if isinstance(value, int):
                        # Old format: single game ID
                        needs_migration = True
                        new_channels[channel_id] = [value]  # Convert to list
                        migrated_channels += 1
                        log.debug(f"Migrating {guild.name} channel {channel_id}: {value} -> [{value}]")
                    elif isinstance(value, list):
                        # Already new format
                        new_channels[channel_id] = value
                    else:
                        # Unknown format, skip
                        log.warning(f"Unknown channel format for {guild.name} channel {channel_id}: {type(value)}")
                        continue
                
                if needs_migration:
                    await guild_config.channels.set(new_channels)
                    migrated_guilds += 1
                    log.info(f"Migrated {guild.name}: {len([k for k, v in channels.items() if isinstance(v, int)])} channels")
                
            except Exception as e:
                log.error(f"Error migrating guild {guild.name}: {e}")
                continue
        
        # Store backup data for potential rollback
        if backup_data:
            await self.config.backup_data.set(backup_data)
            log.info(f"Backup data stored for {len(backup_data)} guilds")
        
        log.info(f"Migration complete: {migrated_guilds} guilds, {migrated_channels} channels migrated")

    async def _fetch_detectable_games(self) -> Dict[str, Dict]:
        """Fetch detectable games from Discord API with caching."""
        if (self._detectable_games_cache is not None and 
            self._cache_expiry is not None and 
            datetime.now() < self._cache_expiry):
            return self._detectable_games_cache
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(detectable_api_url) as response:
                    if response.status == 200:
                        games_data = await response.json()
                        # Create lookup dictionaries for faster searching
                        games_by_id = {game["id"]: game for game in games_data}
                        games_by_name = {game["name"].lower(): game for game in games_data}
                        
                        # Add aliases to name lookup
                        for game in games_data:
                            for alias in game.get("aliases", []):
                                games_by_name[alias.lower()] = game
                        
                        self._detectable_games_cache = {
                            "by_id": games_by_id,
                            "by_name": games_by_name
                        }
                        # Cache for 1 hour
                        self._cache_expiry = datetime.now() + timedelta(hours=1)
                        return self._detectable_games_cache
                    else:
                        log.error(f"Failed to fetch detectable games: {response.status}")
                        return {"by_id": {}, "by_name": {}}
        except Exception as e:
            log.error(f"Error fetching detectable games: {e}")
            return {"by_id": {}, "by_name": {}}

    async def resolve_game_id(self, game_input: str) -> Optional[int]:
        """Resolve a game name or ID to a game ID."""
        games_cache = await self._fetch_detectable_games()
        
        # Try as direct ID first
        if game_input.isdigit():
            if game_input in games_cache["by_id"]:
                return int(game_input)
        
        # Try as name (case insensitive)
        game_input_lower = game_input.lower()
        if game_input_lower in games_cache["by_name"]:
            return int(games_cache["by_name"][game_input_lower]["id"])
        
        return None

    async def get_game_info(self, game_id: int) -> Optional[Dict]:
        """Get game information by ID."""
        games_cache = await self._fetch_detectable_games()
        return games_cache["by_id"].get(str(game_id))

    async def search_games(self, query: str, limit: int = 10) -> List[Dict]:
        """Search for games by name or alias."""
        games_cache = await self._fetch_detectable_games()
        query_lower = query.lower()
        matches = []
        
        for game in games_cache["by_id"].values():
            if (query_lower in game["name"].lower() or 
                any(query_lower in alias.lower() for alias in game.get("aliases", []))):
                matches.append(game)
                if len(matches) >= limit:
                    break
        
        return matches


# region methods

# lang.get("response.birthday_set").format(month=dt_birthday.month,day=dt_birthday.day)

    async def add_game_to_channel(self, guild_id: int, channel_id: int, game_id: int):
        """Add a game requirement to a channel."""
        guild_config = self.config.guild_from_id(guild_id)
        async with guild_config.channels() as channels:
            if channel_id not in channels:
                channels[channel_id] = []
            if game_id not in channels[channel_id]:
                channels[channel_id].append(game_id)

    async def remove_game_from_channel(self, guild_id: int, channel_id: int, game_id: int):
        """Remove a specific game requirement from a channel."""
        guild_config = self.config.guild_from_id(guild_id)
        async with guild_config.channels() as channels:
            if channel_id in channels and game_id in channels[channel_id]:
                channels[channel_id].remove(game_id)
                if not channels[channel_id]:  # Remove channel if no games left
                    channels.pop(channel_id, None)

    async def remove_all_games_from_channel(self, guild_id: int, channel_id: int):
        """Remove all game requirements from a channel."""
        guild_config = self.config.guild_from_id(guild_id)
        async with guild_config.channels() as channels:
            channels.pop(channel_id, None)

    async def get_channel_games(self, guild_id: int, channel_id: int) -> List[int]:
        """Get all game IDs for a channel."""
        guild_config = self.config.guild_from_id(guild_id)
        channels = await guild_config.channels()
        return channels.get(channel_id, [])

    def game_info_str(self, game_info: Optional[Dict], game_id: int) -> str:
        """Format game information as 'Name (ID)' or 'ID' if no info available."""
        if game_info:
            return f"{game_info['name']} ({game_info['id']})"
        return f"ID {game_id}"

    @checks.admin_or_permissions(manage_channels=True)
    @commands.group(name="gamechannel", aliases=["gc"])
    async def game_channel(self, ctx: commands.Context):
        """Manage voice channel game requirements."""
        pass

    @game_channel.command(name="add")
    async def add_game(self, ctx: commands.Context, channel: discord.VoiceChannel, *, game_name: str):
        """Add a game requirement to a voice channel."""
        if not isinstance(channel, discord.VoiceChannel):
            await ctx.send(error("Please specify a voice channel."))
            return
        
        # Resolve game name to ID
        game_id = await self.resolve_game_id(game_name)
        if not game_id:
            # Try to find similar games
            similar_games = await self.search_games(game_name, limit=5)
            if similar_games:
                embed = discord.Embed(
                    title="Game not found",
                    description=f"Could not find '{game_name}'. Did you mean one of these?",
                    color=discord.Color.orange()
                )
                for game in similar_games:
                    embed.add_field(
                        name=game["name"],
                        value=f"ID: {game['id']}",
                        inline=False
                    )
                await ctx.send(embed=embed)
            else:
                await ctx.send(error(f"Game '{game_name}' not found. Use `{ctx.prefix}gc search <name>` to search for games."))
            return
        
        # Add game to channel
        await self.add_game_to_channel(ctx.guild.id, channel.id, game_id)
        
        # Get game info for display
        game_info = await self.get_game_info(game_id)
        game_display = self.game_info_str(game_info, game_id)
        
        await ctx.send(
            success(f"Added {game_display} as a required game for {channel.mention}")
        )

    @game_channel.command(name="remove")
    async def remove_game(self, ctx: commands.Context, channel: discord.VoiceChannel, *, game_name: str):
        """Remove a specific game requirement from a voice channel."""
        if not isinstance(channel, discord.VoiceChannel):
            await ctx.send(error("Please specify a voice channel."))
            return
        
        # Resolve game name to ID
        game_id = await self.resolve_game_id(game_name)
        if not game_id:
            await ctx.send(error(f"Game '{game_name}' not found."))
            return
        
        # Check if game is assigned to channel
        channel_games = await self.get_channel_games(ctx.guild.id, channel.id)
        if game_id not in channel_games:
            await ctx.send(warning(f"{channel.mention} doesn't have '{game_name}' as a requirement."))
            return
        
        # Remove game from channel
        await self.remove_game_from_channel(ctx.guild.id, channel.id, game_id)
        
        # Get game info for display
        game_info = await self.get_game_info(game_id)
        game_display = self.game_info_str(game_info, game_id)
        
        await ctx.send(
            success(f"Removed {game_display} from {channel.mention}")
        )

    @game_channel.command(name="clear")
    async def clear_games(self, ctx: commands.Context, channel: discord.VoiceChannel):
        """Remove all game requirements from a voice channel."""
        if not isinstance(channel, discord.VoiceChannel):
            await ctx.send(error("Please specify a voice channel."))
            return
        
        channel_games = await self.get_channel_games(ctx.guild.id, channel.id)
        if not channel_games:
            await ctx.send(warning(f"{channel.mention} has no game requirements."))
            return
        
        await self.remove_all_games_from_channel(ctx.guild.id, channel.id)
        await ctx.send(success(f"Removed all game requirements from {channel.mention}"))

    @game_channel.command(name="check")
    async def gamechannel_check(self, ctx: commands.Context):
        """Check all users in game-restricted voice channels and remove those not playing any required game."""
        if not ctx.guild:
            await ctx.send("This command can only be used in a server.")
            return
        
        removed_users = 0
        checked_channels = 0
        
        # Get all guilds if command is used by bot owner, otherwise just the current guild
        guilds = self.bot.guilds if await self.bot.is_owner(ctx.author) else [ctx.guild]
        
        status_message = await ctx.send("Checking voice channels for users not playing required games...")
        
        for guild in guilds:
            channels = await self.config.guild(guild).channels()
            if not channels:
                continue
                
            for channel_id, required_game_ids in channels.items():
                channel = guild.get_channel(int(channel_id))
                if not channel or not isinstance(channel, discord.VoiceChannel):
                    continue
                    
                checked_channels += 1
                
                for member in channel.members:
                    activities = [
                        activity.application_id 
                        for activity in member.activities 
                        if isinstance(activity, discord.Activity) and activity.application_id
                    ]
                    
                    # Check if member is playing any of the required games
                    if not any(game_id in activities for game_id in required_game_ids):
                        try:
                            # Get game names for the message
                            game_names = []
                            for game_id in required_game_ids:
                                game_info = await self.get_game_info(game_id)
                                game_names.append(self.game_info_str(game_info, game_id))
                            
                            games_list = ", ".join(game_names)
                            await member.send(f"You were removed from {channel.mention} because you weren't playing any of the required games: {games_list}")
                        except discord.Forbidden:
                            pass
                            
                        try:
                            await member.edit(voice_channel=None)
                            removed_users += 1
                        except discord.Forbidden:
                            log.warning(f"Could not remove {member} from {channel} in {guild} due to permissions.")
        
        await status_message.delete()
        await ctx.send(f"Check complete! Checked {checked_channels} channels across {len(guilds)} servers and removed {removed_users} users not playing required games.")

    @game_channel.command(name="list")
    async def gamechannel_list(self, ctx: commands.Context):
        """List all voice channels with game requirements."""
        if not ctx.guild:
            await ctx.send("This command can only be used in a server.")
            return
        channels = await self.config.guild(ctx.guild).channels()
        if not channels:
            await ctx.send("No voice channels have game requirements set.")
            return
        
        embed = discord.Embed(title="Voice Channel Game Requirements")
        for channel_id, game_ids in channels.items():
            channel = ctx.guild.get_channel(int(channel_id))
            if channel and game_ids:
                # Get game names
                game_names = []
                for game_id in game_ids:
                    game_info = await self.get_game_info(game_id)
                    game_names.append(self.game_info_str(game_info, game_id))
                
                embed.add_field(
                    name=f"{channel.mention}",
                    value=f"Required Games: {', '.join(game_names)}",
                    inline=False
                )
        await ctx.send(embed=embed)

    @game_channel.command(name="search")
    async def search_games(self, ctx: commands.Context, *, query: str):
        """Search for games by name."""
        if len(query) < 2:
            await ctx.send(error("Query must be at least 2 characters long."))
            return
        
        games = await self.search_games(query, limit=10)
        if not games:
            await ctx.send(error(f"No games found matching '{query}'."))
            return
        
        embed = discord.Embed(
            title=f"Games matching '{query}'",
            color=discord.Color.blue()
        )
        
        for game in games:
            themes = ", ".join(game.get("themes", [])) if game.get("themes") else "No themes"
            embed.add_field(
                name=game["name"],
                value=f"ID: {game['id']}\nThemes: {themes}",
                inline=True
            )
        
        await ctx.send(embed=embed)

    @game_channel.command(name="info")
    async def game_info(self, ctx: commands.Context, *, game_name: str):
        """Get detailed information about a game."""
        game_id = await self.resolve_game_id(game_name)
        if not game_id:
            await ctx.send(error(f"Game '{game_name}' not found."))
            return
        
        game_info = await self.get_game_info(game_id)
        if not game_info:
            await ctx.send(error(f"Could not retrieve information for game ID {game_id}."))
            return
        
        embed = discord.Embed(
            title=self.game_info_str(game_info, game_id),
            color=discord.Color.green()
        )
        
        if game_info.get("aliases"):
            embed.add_field(name="Aliases", value=", ".join(game_info["aliases"]), inline=False)
        
        if game_info.get("themes"):
            embed.add_field(name="Themes", value=", ".join(game_info["themes"]), inline=False)
        
        embed.add_field(name="Game ID", value=game_info["id"], inline=True)
        embed.add_field(name="Overlay Support", value="Yes" if game_info.get("overlay") else "No", inline=True)
        embed.add_field(name="Hook Support", value="Yes" if game_info.get("hook") else "No", inline=True)
        
        if game_info.get("executables"):
            exe_names = [exe["name"] for exe in game_info["executables"][:5]]  # Limit to 5
            exe_text = ", ".join(exe_names)
            if len(game_info["executables"]) > 5:
                exe_text += f" (+{len(game_info['executables']) - 5} more)"
            embed.add_field(name="Executables", value=exe_text, inline=False)
        
        await ctx.send(embed=embed)

    @game_channel.command(name="reload")
    async def reload_cache(self, ctx: commands.Context):
        """Reload the game cache from Discord's API."""
        await ctx.send("Reloading game cache...")
        
        # Clear the cache to force a reload
        self._detectable_games_cache = None
        self._cache_expiry = None
        
        # Fetch fresh data
        games_cache = await self._fetch_detectable_games()
        
        if games_cache and games_cache.get("by_id"):
            game_count = len(games_cache["by_id"])
            await ctx.send(success(f"Successfully reloaded game cache with {game_count} games."))
        else:
            await ctx.send(error("Failed to reload game cache. Check the logs for details."))

    @game_channel.command(name="cache")
    async def cache_info(self, ctx: commands.Context):
        """Show information about the current game cache."""
        if self._detectable_games_cache is None:
            await ctx.send(info("Game cache is empty. Use `{ctx.prefix}gc reload` to load games."))
            return
        
        game_count = len(self._detectable_games_cache.get("by_id", {}))
        cache_age = "Unknown"
        
        if self._cache_expiry:
            time_remaining = self._cache_expiry - datetime.now()
            if time_remaining.total_seconds() > 0:
                hours, remainder = divmod(int(time_remaining.total_seconds()), 3600)
                minutes, _ = divmod(remainder, 60)
                cache_age = f"{hours}h {minutes}m remaining"
            else:
                cache_age = "Expired"
        
        embed = discord.Embed(
            title="Game Cache Information",
            color=discord.Color.blue()
        )
        embed.add_field(name="Games Cached", value=str(game_count), inline=True)
        embed.add_field(name="Cache Status", value=cache_age, inline=True)
        embed.add_field(name="API Endpoint", value=detectable_api_url, inline=False)
        
        await ctx.send(embed=embed)

    @game_channel.command(name="find")
    async def find_games(self, ctx: commands.Context, *, query: str):
        """Search the game cache with detailed results."""
        if len(query) < 2:
            await ctx.send(error("Query must be at least 2 characters long."))
            return
        
        # Ensure cache is loaded
        games_cache = await self._fetch_detectable_games()
        if not games_cache or not games_cache.get("by_id"):
            await ctx.send(error("Game cache is not available. Use `{ctx.prefix}gc reload` to load games."))
            return
        
        # Search for games
        query_lower = query.lower()
        matches = []
        
        for game in games_cache["by_id"].values():
            # Check name match
            name_match = query_lower in game["name"].lower()
            # Check alias matches
            alias_matches = any(query_lower in alias.lower() for alias in game.get("aliases", []))
            
            if name_match or alias_matches:
                # Calculate match score (exact name match gets higher score)
                score = 0
                if game["name"].lower() == query_lower:
                    score = 100  # Exact name match
                elif game["name"].lower().startswith(query_lower):
                    score = 80   # Name starts with query
                elif name_match:
                    score = 60   # Name contains query
                elif alias_matches:
                    score = 40   # Alias contains query
                
                matches.append((score, game))
        
        # Sort by score (highest first) and limit results
        matches.sort(key=lambda x: x[0], reverse=True)
        matches = matches[:15]  # Limit to 15 results
        
        if not matches:
            await ctx.send(error(f"No games found matching '{query}'."))
            return
        
        # Create embed with results
        embed = discord.Embed(
            title=f"Game Search Results for '{query}'",
            description=f"Found {len(matches)} game(s)",
            color=discord.Color.green()
        )
        
        for score, game in matches:
            # Format game info
            themes = ", ".join(game.get("themes", [])) if game.get("themes") else "No themes"
            aliases = ", ".join(game.get("aliases", [])) if game.get("aliases") else "No aliases"
            
            # Create field value
            field_value = f"**ID:** {game['id']}\n"
            field_value += f"**Themes:** {themes}\n"
            if aliases != "No aliases":
                field_value += f"**Aliases:** {aliases}\n"
            field_value += f"**Overlay:** {'Yes' if game.get('overlay') else 'No'} | "
            field_value += f"**Hook:** {'Yes' if game.get('hook') else 'No'}"
            
            # Truncate if too long
            if len(field_value) > 1000:
                field_value = field_value[:997] + "..."
            
            embed.add_field(
                name=f"{game['name']} (Score: {score})",
                value=field_value,
                inline=False
            )
        
        # Add footer with usage info
        embed.set_footer(text=f"Use '{ctx.prefix}gc add <channel> <game_name>' to add a game to a channel")
        
        await ctx.send(embed=embed)

    @game_channel.command(name="migrate")
    @checks.is_owner()
    async def migrate_config(self, ctx: commands.Context):
        """Manually trigger configuration migration (Bot Owner only)."""
        current_version = await self.config.schema_version()
        latest_version = 1
        
        if current_version >= latest_version:
            await ctx.send(info(f"Configuration is already at the latest version ({current_version})."))
            return
        
        await ctx.send("Starting configuration migration...")
        
        try:
            if current_version < 1:
                await self._migrate_to_v1()
                await self.config.schema_version.set(1)
                await ctx.send(success("Successfully migrated to schema version 1!"))
            else:
                await ctx.send(info("No migration needed."))
                
        except Exception as e:
            await ctx.send(error(f"Migration failed: {e}"))
            log.error(f"Manual migration failed: {e}")

    @game_channel.command(name="version")
    async def config_version(self, ctx: commands.Context):
        """Show the current configuration schema version."""
        current_version = await self.config.schema_version()
        latest_version = 1
        
        embed = discord.Embed(
            title="Configuration Schema Version",
            color=discord.Color.blue()
        )
        embed.add_field(name="Current Version", value=str(current_version), inline=True)
        embed.add_field(name="Latest Version", value=str(latest_version), inline=True)
        
        if current_version < latest_version:
            embed.color = discord.Color.orange()
            embed.add_field(
                name="Status", 
                value="⚠️ Migration needed", 
                inline=False
            )
            embed.add_field(
                name="Action", 
                value=f"Use `{ctx.prefix}gc migrate` to update", 
                inline=False
            )
        else:
            embed.color = discord.Color.green()
            embed.add_field(name="Status", value="✅ Up to date", inline=False)
        
        await ctx.send(embed=embed)

    @game_channel.command(name="rollback")
    @checks.is_owner()
    async def rollback_migration(self, ctx: commands.Context):
        """Rollback to previous configuration (Bot Owner only)."""
        backup_data = await self.config.backup_data()
        
        if not backup_data:
            await ctx.send(error("No backup data found. Cannot rollback."))
            return
        
        await ctx.send("⚠️ **WARNING**: This will restore the previous configuration and may cause data loss. Continue? (yes/no)")
        
        def check(message):
            return (message.author == ctx.author and 
                   message.channel == ctx.channel and 
                   message.content.lower() in ['yes', 'no'])
        
        try:
            response = await self.bot.wait_for('message', check=check, timeout=30.0)
            if response.content.lower() != 'yes':
                await ctx.send("Rollback cancelled.")
                return
        except asyncio.TimeoutError:
            await ctx.send("Rollback cancelled due to timeout.")
            return
        
        try:
            rollback_count = 0
            for guild_id_str, channels in backup_data.items():
                guild_id = int(guild_id_str)
                guild = self.bot.get_guild(guild_id)
                if guild:
                    guild_config = self.config.guild(guild)
                    await guild_config.channels.set(channels)
                    rollback_count += 1
            
            # Reset schema version
            await self.config.schema_version.set(0)
            
            await ctx.send(success(f"Successfully rolled back configuration for {rollback_count} guilds."))
            log.info(f"Configuration rolled back for {rollback_count} guilds")
            
        except Exception as e:
            await ctx.send(error(f"Rollback failed: {e}"))
            log.error(f"Rollback failed: {e}")

    @game_channel.command(name="backup")
    @checks.is_owner()
    async def backup_config(self, ctx: commands.Context):
        """Create a backup of current configuration (Bot Owner only)."""
        backup_data = {}
        
        for guild in self.bot.guilds:
            try:
                guild_config = self.config.guild(guild)
                channels = await guild_config.channels()
                if channels:
                    backup_data[str(guild.id)] = dict(channels)
            except Exception as e:
                log.error(f"Error backing up guild {guild.name}: {e}")
                continue
        
        await self.config.backup_data.set(backup_data)
        
        await ctx.send(success(f"Backup created for {len(backup_data)} guilds with game channel configurations."))
        log.info(f"Manual backup created for {len(backup_data)} guilds")
            
# endregion metods

# region events
    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState
    ):
        if not after.channel:
            return

        channel_id = str(after.channel.id)

        guild_config = self.config.guild(member.guild)
        channels = await guild_config.channels()
        
        if channel_id not in channels: 
            return

        required_game_ids = channels[channel_id]
        if not required_game_ids:
            return
        
        activities = [ activity.application_id for activity in member.activities if isinstance(activity, discord.Activity) ]

        # Check if member is playing any of the required games
        is_playing_required_game = any(game_id in activities for game_id in required_game_ids)
        
        log.info(f"[#{channel_id}] @{member.id}: {required_game_ids} in {activities} == {is_playing_required_game}")
        
        if not is_playing_required_game:
            chan = after.channel.mention
            
            # Get game names for the message
            game_names = []
            for game_id in required_game_ids:
                game_info = await self.get_game_info(game_id)
                game_names.append(self.game_info_str(game_info, game_id))
            
            games_list = ", ".join(game_names)
            
            try:
                await member.edit(voice_channel=None)
                await member.send(f"You were removed from {chan} because you weren't playing any of the required games: {games_list}")
            except discord.Forbidden:
                log.warning(f"Could not remove {member} from {chan} due to permissions.")
# endregion events

    @staticmethod
    async def send_embed(
        channel_or_ctx: commands.Context | discord.TextChannel,
        embed: discord.Embed,
    ) -> bool:
        """Send an embed. If the bot can't send it, complains about permissions."""
        destination = (
            channel_or_ctx.channel
            if isinstance(channel_or_ctx, commands.Context)
            else channel_or_ctx
        )
        if (
            hasattr(destination, "guild")
            and destination.guild
            and not destination.permissions_for(destination.guild.me).embed_links
        ):
            await destination.send(
                error("I need the `Embed links` permission to function properly")
            )
            return False
        await destination.send(embed=embed)
        return True

    @staticmethod
    def embed_maker(
        title: str | None,
        color: discord.Colour | None,
        description: str | None,
        avatar: str | None = None,
    ) -> discord.Embed:
        """Create a nice embed."""
        embed = discord.Embed(title=title, color=color, description=description)
        if avatar:
            embed.set_thumbnail(url=avatar)
        return embed
