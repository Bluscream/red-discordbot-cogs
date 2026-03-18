"""UEVR Webhooks cog for Red-DiscordBot"""

import asyncio
import aiohttp
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

log = getLogger("red.blu.uevr_webhooks")

class UEVRWebhooks(commands.Cog):
    """
    Monitors Discord forums and triggers external webhooks on archve attachments.
    """

    __author__ = "Bluscream"
    __version__ = "1.0.0"

    default_global_settings: ClassVar[dict[str, Union[int, dict, List[int], List[str]]]] = {
        "monitored_channels": [1062167556129030164, 1199859776352428062, 1203329945770659861],
        "discord_webhooks": ["https://discord.com/api/webhooks/1483609828638064786/X4nSLVFPu9rq8nUjb_Q6C65QnC_AL85iH4CgEVyYeg-_ZDnv6ax0VdRQoYILtiio7At2"],
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

    @commands.group(name="uevrwebhooks", aliases=["uwh"])
    async def uevrwebhooks(self, ctx: commands.Context):
        """Manage UEVR Webhook configuration."""
        pass

    import json
    
    @commands.group(name="uevrwebhooks", aliases=["uwh"])
    async def uevrwebhooks(self, ctx: commands.Context):
        """Manage UEVR Webhook configuration."""
        pass

    @uevrwebhooks.group(name="settings")
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

    @tasks.loop(minutes=30)
    async def polling_task(self):
        """Poll external APIs for new profiles."""
        log.debug("[UEVR Webhooks] Starting polling cycle.")
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
                    self.trigger_discord(sub_profile),
                    self.trigger_hass(sub_profile),
                    self.trigger_github(sub_profile)
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
            
        log.info(f"[UEVR Webhooks] Detected new profile archive in #{message.channel.name} by {message.author}. Triggering webhooks.")

        for archive in new_archives:
            # 1. Download and Inspect before triggering
            await archive.download_and_inspect(self.session)
            
            # 2. Trigger webhooks for every distinct profile discovered inside the archive
            for sub_profile in archive.profiles:
                await asyncio.gather(
                    self.trigger_discord(sub_profile),
                    self.trigger_hass(sub_profile),
                    self.trigger_github(sub_profile)
                )
                await asyncio.sleep(1)

    async def trigger_discord(self, profile: UEVRProfile):
        hooks = await self.config.discord_webhooks()
        if not hooks: return

        embed_payload = profile.to_discord_embed()
            
        for webhook_url in hooks:
            for _ in range(3):
                try:
                    # Basic aiohttp dispatch to Discord Webhook
                    json_data = {"embeds": [embed_payload]}
                    async with self.session.post(webhook_url, json=json_data) as resp:
                        if resp.status == 429:
                            try:
                                data = await resp.json()
                                retry_after = data.get('retry_after', float(resp.headers.get('Retry-After', 1.0)))
                            except:
                                retry_after = 1.0
                            log.warning(f"[UEVR Webhooks] Discord rate limited (429). Retrying in {retry_after}s...")
                            await asyncio.sleep(retry_after + 1)
                            continue
                        elif resp.status >= 400:
                            log.warning(f"[UEVR Webhooks] Discord webhook returned error: {resp.status}")
                        break
                except Exception as e:
                    log.error(f"[UEVR Webhooks] Failed to trigger Discord webhook: {e}")
                    break

    async def trigger_hass(self, profile: UEVRProfile):
        hooks = await self.config.hass_webhooks()
        if not hooks: return
        
        payload = profile.to_hass_payload()
        
        for webhook_url in hooks:
            try:
                async with self.session.post(webhook_url, json=payload) as resp:
                    if resp.status >= 400:
                        log.warning(f"[UEVR Webhooks] Home Assistant webhook returned error: {resp.status}")
            except Exception as e:
                log.error(f"[UEVR Webhooks] Failed to trigger Home Assistant webhook: {e}")

    async def trigger_github(self, profile: UEVRProfile):
        hooks = await self.config.github_webhooks()
        token = await self.config.github_token()
        if not hooks or not token: return
        
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "Authorization": f"Bearer {token}"
        }
        
        github_payload = profile.to_github_payload()

        for webhook_url in hooks:
            if not webhook_url: continue
            try:
                async with self.session.post(webhook_url, headers=headers, json=github_payload) as resp:
                    if resp.status >= 400:
                        log.warning(f"[UEVR Webhooks] GitHub webhook returned error: {resp.status}")
            except Exception as e:
                log.error(f"[UEVR Webhooks] Failed to trigger GitHub webhook: {e}")
