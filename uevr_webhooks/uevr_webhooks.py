"""UEVR Webhooks cog for Red-DiscordBot"""

import asyncio
import aiohttp
import json
from typing import ClassVar, Dict, List, Optional, Union
from logging import getLogger
from datetime import datetime

import discord
from redbot.core import Config, checks, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import error, info, success, warning, box
from discord.ext import tasks

from .sources import DiscordSource, UEVRDeluxeSource, UEVRProfilesSource
from .models import UEVRArchive, UEVRProfile
from .targets import (
    DiscordChannelTarget, 
    DiscordWebhookTarget, 
    GenericWebhookTarget, 
    GitHubTarget
)

log = getLogger("red.blu.uevr_webhooks")

class UEVRWebhooks(commands.Cog):
    """
    Monitors Discord forums and triggers external webhooks on archve attachments.
    """

    __author__ = "Bluscream"
    __version__ = "1.0.0"

    default_global_settings: ClassVar[dict[str, Union[int, dict, List[int], List[str]]]] = {
        "monitored_channels": [1062167556129030164, 1199859776352428062, 1203329945770659861],
        "discord_channels": [1483609737198047424],
        "discord_webhooks": [],
        "hass_webhooks": ["https://hass.minopia.de/api/webhook/-c7d3VKBdgySzs6SIng5mMzCT"],
        "github_webhooks": [""],
        "github_token": "",
        "poll_interval_minutes": 30,
        "cached_profiles": {} # unique_id -> timestamp
    }

    def __init__(self, bot: Red) -> None:
        """Set up the cog."""
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=928374562, force_registration=True
        )
        self.config.register_global(**self.default_global_settings)
        self.session = aiohttp.ClientSession()
        
        self.deluxe_source = UEVRDeluxeSource()
        self.profiles_source = UEVRProfilesSource()
        
        # Initialize Dispatch Targets
        self.target_discord_chan = DiscordChannelTarget(bot)
        self.target_discord_web = DiscordWebhookTarget()
        self.target_generic_web = GenericWebhookTarget()
        self.target_github = GitHubTarget(token_provider=self.config.github_token)
        
        self.polling_task.start()

    def cog_unload(self):
        self.polling_task.cancel()
        self.bot.loop.create_task(self.session.close())

    async def cog_load(self) -> None:
        """Called when the cog is loaded."""
        log.info("UEVR Webhooks cog loaded successfully")

    def _build_message_link_from_msg(self, message: discord.Message) -> str:
        """Build a Discord message link from a message object."""
        return f"https://discord.com/channels/{message.guild.id}/{message.channel.id}/{message.id}"


    @commands.group(name="uevr", aliases=["uwh"], invoke_without_command=True)
    async def uevr_base(self, ctx: commands.Context):
        """Base command for UEVR bot functions."""
        await ctx.send_help()

    @uevr_base.group(name="settings")
    @commands.is_owner()
    async def uwh_settings(self, ctx: commands.Context):
        """Dynamic Key/Value store for UEVR Webhook configuration."""
        pass

    @uwh_settings.command(name="set")
    async def settings_set(self, ctx: commands.Context, key: str, *, value: str):
        """Set a configuration value. Supports JSON dicts '{}' and lists '[]'."""
        try:
            parsed_value = json.loads(value)
        except json.JSONDecodeError:
            # If it's not valid JSON, treat it as a raw string (or int if it looks like one)
            if value.isdigit():
                parsed_value = int(value)
            else:
                parsed_value = value
                
        await self.config.set_raw(key, value=parsed_value)
        await ctx.message.delete()
        await ctx.send(success(f"Successfully set `{key}`."))

    @uwh_settings.command(name="add")
    async def settings_add(self, ctx: commands.Context, key: str, *, value: str):
        """Append a value to a configuration list."""
        try:
            parsed_value = json.loads(value)
        except json.JSONDecodeError:
            if value.isdigit():
                parsed_value = int(value)
            else:
                parsed_value = value
                
        # Handle fetching and appending
        current = await self.config.get_raw(key, default=[])
        if not isinstance(current, list):
            await ctx.send(error(f"The key `{key}` does not contain a list. Use `set` instead."))
            return
            
        if parsed_value not in current:
            current.append(parsed_value)
            await self.config.set_raw(key, value=current)
            await ctx.send(success(f"Added value to `{key}` list."))
        else:
            await ctx.send(warning(f"That value is already inside the `{key}` list."))
        await ctx.message.delete()

    @uwh_settings.command(name="remove")
    async def settings_remove(self, ctx: commands.Context, key: str, *, value: str):
        """Remove a value from a configuration list."""
        try:
            parsed_value = json.loads(value)
        except json.JSONDecodeError:
            if value.isdigit():
                parsed_value = int(value)
            else:
                parsed_value = value

        current = await self.config.get_raw(key, default=[])
        if not isinstance(current, list):
            await ctx.send(error(f"The key `{key}` does not contain a list."))
            return
            
        if parsed_value in current:
            current.remove(parsed_value)
            await self.config.set_raw(key, value=current)
            await ctx.send(success(f"Removed value from `{key}` list."))
        else:
            await ctx.send(warning(f"Value not found in `{key}` list."))
        await ctx.message.delete()

    @uwh_settings.command(name="get")
    async def settings_get(self, ctx: commands.Context, key: str):
        """View the current value or list for a given key."""
        try:
            current_value = await self.config.get_raw(key)
            formatted = json.dumps(current_value, indent=4)
            await ctx.send(box(formatted, lang="json"))
        except KeyError:
            await ctx.send(error(f"Key `{key}` not found in config."))

    @uwh_settings.command(name="list")
    async def settings_list(self, ctx: commands.Context):
        """List all configured keys and their current values."""
        all_data = await self.config.all()
        
        # Omit massive cached_profiles object if it exists to prevent spam
        if "cached_profiles" in all_data:
            all_data["cached_profiles"] = f"<Cache containing {len(all_data['cached_profiles'])} items hidden>"
            
        formatted = json.dumps(all_data, indent=4)
        if len(formatted) > 1900:
            import io
            file = discord.File(io.StringIO(formatted), filename="uevr_config.json")
            await ctx.send(file=file)
        else:
            await ctx.send(box(formatted, lang="json"))

    @uwh_settings.command(name="clear")
    async def settings_clear(self, ctx: commands.Context, key: str):
        """Reset a configuration key back to its default value or delete it."""
        try:
            await self.config.clear_raw(key)
            await ctx.send(success(f"Cleared the configuration for `{key}`."))
        except KeyError:
            await ctx.send(error(f"Key `{key}` not found."))


    @uevr_base.command(name="clear")
    @checks.admin_or_permissions(manage_messages=True)
    async def clear_channels(self, ctx: commands.Context):
        """Purge all bot and webhook messages in the configured discord_channels list."""
        channels = await self.config.discord_channels()
        webhook_urls = await self.config.discord_webhooks()
        
        if not channels:
            return await ctx.send(warning("No discord_channels are currently configured for posting."))
            
        import re
        webhook_ids = set()
        for url in webhook_urls:
            match = re.search(r"webhooks/(\d+)/", url)
            if match:
                webhook_ids.add(int(match.group(1)))

        await ctx.send(info(f"Attempting to clear bot and webhook messages in {len(channels)} configured channel(s)..."))
        
        def purge_check(m: discord.Message):
            if m.author == self.bot.user:
                return True
            if m.webhook_id and m.webhook_id in webhook_ids:
                return True
            return False

        cleared_count = 0
        for chan_id in channels:
            channel = self.bot.get_channel(chan_id)
            if not channel:
                continue
            
            try:
                # Purge messages authored by this bot or our webhooks
                deleted = await channel.purge(limit=1000, check=purge_check)
                cleared_count += len(deleted)
            except discord.Forbidden:
                await ctx.send(error(f"I don't have permission to manage messages in <#{chan_id}>."))
            except discord.HTTPException as e:
                await ctx.send(error(f"Failed to clear <#{chan_id}>: {e}"))
                
        await ctx.send(success(f"Successfully cleared {cleared_count} bot/webhook message(s) from posting channels."))

    @tasks.loop(minutes=30)
    async def polling_task(self):
        """Poll external APIs for new profiles."""
        log.info("[UEVR Webhooks] Starting polling cycle (v1.0.0).")
        cache = await self.config.cached_profiles()
        
        # Combine requests
        deluxe_archives = await self.deluxe_source.fetch_new_archives(self.session, known_ids=set(cache.keys()))
        profiles_archives = await self.profiles_source.fetch_new_archives(self.session, known_ids=set(cache.keys()))
        
        all_new_archives: List[UEVRArchive] = deluxe_archives + profiles_archives
        
        if not all_new_archives:
            return
            
        newly_processed = {}
        for archive in all_new_archives:
            # 1. Download and Inspect
            await archive.download_and_inspect(self.session)
            
            # 2. Trigger webhooks for every distinct profile discovered inside the archive
            for sub_profile in archive.profiles:
                await asyncio.gather(
                    self.target_discord_chan.send(sub_profile, self.session, await self.config.discord_channels()),
                    self.target_discord_web.send(sub_profile, self.session, await self.config.discord_webhooks()),
                    self.target_generic_web.send(sub_profile, self.session, await self.config.hass_webhooks()),
                    self.target_github.send(sub_profile, self.session, await self.config.github_webhooks())
                )
                await asyncio.sleep(2.0)
            
            # 3. Mark processed
            newly_processed[archive.unique_id] = datetime.utcnow().timestamp()
            
        # Update cache
        async with self.config.cached_profiles() as active_cache:
            active_cache.update(newly_processed)
            
        log.info(f"[UEVR Webhooks] Polling cycle complete. Discovered and broadcast {len(all_new_archives)} new archives.")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Trigger webhooks on new profile zip attachments."""
        if message.author.bot:
            return

        monitored = await self.config.monitored_channels()
        # Verify the message aligns with our watched locations
        valid_location = False
        if message.channel.id in monitored:
            valid_location = True
        elif hasattr(message.channel, "parent_id") and message.channel.parent_id in monitored:
            valid_location = True
            
        if not valid_location:
            return
            
        # Use DiscordSource to parse the message into UEVRArchives
        new_archives = DiscordSource.parse_message(message)
        if not new_archives:
            return
            
        cache = await self.config.cached_profiles()
        
        unique_archives = []
        for arch in new_archives:
            if str(arch.unique_id) not in cache:
                unique_archives.append(arch)
                
        if not unique_archives:
            return
            
        log.info(f"[UEVR Webhooks] Detected {len(unique_archives)} new profile archive(s) in #{message.channel.name} by {message.author}. Triggering webhooks.")

        newly_processed = {}
        for archive in unique_archives:
            # 1. Download and Inspect before triggering
            await archive.download_and_inspect(self.session)
            
            # 2. Trigger webhooks for every distinct profile discovered inside the archive
            for sub_profile in archive.profiles:
                await asyncio.gather(
                    self.target_discord_chan.send(sub_profile, self.session, await self.config.discord_channels()),
                    self.target_discord_web.send(sub_profile, self.session, await self.config.discord_webhooks()),
                    self.target_generic_web.send(sub_profile, self.session, await self.config.hass_webhooks()),
                    self.target_github.send(sub_profile, self.session, await self.config.github_webhooks())
                )
                await asyncio.sleep(1)
                
            # 3. Mark processed in cache mapping
            newly_processed[archive.unique_id] = message.created_at.timestamp()

        # Update persistent store
        if newly_processed:
            async with self.config.cached_profiles() as active_cache:
                active_cache.update(newly_processed)

    # Target handling methods are now modularized into .targets folder.
    # The old trigger_* methods are removed.
