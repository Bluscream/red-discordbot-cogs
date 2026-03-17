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

log = getLogger("red.blu.uevr_webhooks")

class UEVRWebhooks(commands.Cog):
    """
    Monitors Discord forums and triggers external webhooks on archve attachments.
    """

    __author__ = "Bluscream"
    __version__ = "1.0.0"

    default_global_settings: ClassVar[dict[str, Union[int, dict, List[int], List[str]]]] = {
        "monitored_channels": [],
        "discord_webhooks": ["https://discord.com/api/webhooks/1483609828638064786/X4nSLVFPu9rq8nUjb_Q6C65QnC_AL85iH4CgEVyYeg-_ZDnv6ax0VdRQoYILtiio7At2"],
        "hass_webhooks": ["https://hass.minopia.de/api/webhook/-c7d3VKBdgySzs6SIng5mMzCT"],
        "github_webhooks": [""],
        "github_token": ""
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

    def cog_unload(self):
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

    # --- Channel Management ---
    @uevrwebhooks.group(name="channel")
    @commands.is_owner()
    async def uwh_channel(self, ctx: commands.Context):
        """Manage monitored forum channels."""
        pass

    @uwh_channel.command(name="add")
    async def channel_add(self, ctx: commands.Context, channel_id: int):
        """Add a forum channel ID to monitor."""
        async with self.config.monitored_channels() as channels:
            if channel_id not in channels:
                channels.append(channel_id)
                await ctx.send(success(f"Added `<#{channel_id}>` to monitored channels."))
            else:
                await ctx.send(warning(f"Channel `<#{channel_id}>` is already monitored."))

    @uwh_channel.command(name="remove")
    async def channel_remove(self, ctx: commands.Context, channel_id: int):
        """Remove a forum channel ID from monitoring."""
        async with self.config.monitored_channels() as channels:
            if channel_id in channels:
                channels.remove(channel_id)
                await ctx.send(success(f"Removed `<#{channel_id}>` from monitored channels."))
            else:
                await ctx.send(warning(f"Channel `<#{channel_id}>` is not currently monitored."))

    @uwh_channel.command(name="list")
    async def channel_list(self, ctx: commands.Context):
        """List all monitored forum channels."""
        channels = await self.config.monitored_channels()
        if not channels:
            await ctx.send(info("No channels are currently being monitored."))
        else:
            msg = "Monitored channels:\n" + "\n".join(f"- <#{cid}> ({cid})" for cid in channels)
            await ctx.send(msg)

    # --- Discord Webhook Management ---
    @uevrwebhooks.group(name="discord")
    @commands.is_owner()
    async def uwh_discord(self, ctx: commands.Context):
        """Manage Discord Webhook URLs."""
        pass

    @uwh_discord.command(name="add")
    async def discord_add(self, ctx: commands.Context, url: str):
        """Add a Discord Webhook URL."""
        async with self.config.discord_webhooks() as hooks:
            if url not in hooks:
                hooks.append(url)
                await ctx.message.delete()
                await ctx.send(success("Added Discord webhook."))
            else:
                await ctx.send(warning("That Discord webhook is already registered."))

    @uwh_discord.command(name="remove")
    async def discord_remove(self, ctx: commands.Context, url: str):
        """Remove a Discord Webhook URL."""
        async with self.config.discord_webhooks() as hooks:
            if url in hooks:
                hooks.remove(url)
                await ctx.message.delete()
                await ctx.send(success("Removed Discord webhook."))
            else:
                await ctx.send(warning("That Discord webhook was not found."))

    @uwh_discord.command(name="list")
    async def discord_list(self, ctx: commands.Context):
        """List the quantity of registered Discord webhooks."""
        hooks = await self.config.discord_webhooks()
        await ctx.send(info(f"There are currently {len(hooks)} Discord webhooks registered."))

    # --- Home Assistant Webhook Management ---
    @uevrwebhooks.group(name="hass")
    @commands.is_owner()
    async def uwh_hass(self, ctx: commands.Context):
        """Manage Home Assistant Webhook URLs."""
        pass

    @uwh_hass.command(name="add")
    async def hass_add(self, ctx: commands.Context, url: str):
        """Add a Home Assistant Webhook URL."""
        async with self.config.hass_webhooks() as hooks:
            if url not in hooks:
                hooks.append(url)
                await ctx.message.delete()
                await ctx.send(success("Added Home Assistant webhook."))
            else:
                await ctx.send(warning("That Home Assistant webhook is already registered."))

    @uwh_hass.command(name="remove")
    async def hass_remove(self, ctx: commands.Context, url: str):
        """Remove a Home Assistant Webhook URL."""
        async with self.config.hass_webhooks() as hooks:
            if url in hooks:
                hooks.remove(url)
                await ctx.message.delete()
                await ctx.send(success("Removed Home Assistant webhook."))
            else:
                await ctx.send(warning("That Home Assistant webhook was not found."))

    @uwh_hass.command(name="list")
    async def hass_list(self, ctx: commands.Context):
        """List the quantity of registered Home Assistant webhooks."""
        hooks = await self.config.hass_webhooks()
        await ctx.send(info(f"There are currently {len(hooks)} Home Assistant webhooks registered."))

    # --- GitHub Webhook Management ---
    @uevrwebhooks.group(name="github")
    @commands.is_owner()
    async def uwh_github(self, ctx: commands.Context):
        """Manage GitHub Repository Dispatch Webhooks."""
        pass

    @uwh_github.command(name="add")
    async def github_add(self, ctx: commands.Context, url: str, token: str):
        """Add a GitHub Repository Dispatch Webhook URL and Token."""
        async with self.config.github_webhooks() as hooks:
            if url not in hooks:
                hooks.append(url)
            await self.config.github_token.set(token)
            await ctx.message.delete()
            await ctx.send(success("Set GitHub repository dispatch webhook and authorization token."))

    @uwh_github.command(name="remove")
    async def github_remove(self, ctx: commands.Context, url: str):
        """Remove a GitHub Webhook URL."""
        async with self.config.github_webhooks() as hooks:
            if url in hooks:
                hooks.remove(url)
                await ctx.message.delete()
                await ctx.send(success("Removed GitHub webhook."))
            else:
                await ctx.send(warning("That GitHub webhook was not found."))

    @uwh_github.command(name="list")
    async def github_list(self, ctx: commands.Context):
        """List the quantity of registered GitHub webhooks."""
        hooks = await self.config.github_webhooks()
        await ctx.send(info(f"There are currently {len(hooks)} GitHub repository dispatch webhooks registered."))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Trigger webhooks on new profile zip attachments."""
        if message.author.bot:
            return

        monitored = await self.config.monitored_channels()
        # Verify the message aligns with our watched locations
        # Handles threads under forum channels where parent_id holds the actual forum category ID
        valid_location = False
        if message.channel.id in monitored:
            valid_location = True
        elif hasattr(message.channel, "parent_id") and message.channel.parent_id in monitored:
            valid_location = True
            
        if not valid_location:
            return

        # Check for archive attachments
        valid_extensions = ('.zip', '.7z', '.rar')
        valid_attachments = [a for a in message.attachments if any(a.filename.lower().endswith(ext) for ext in valid_extensions)]
        
        if not valid_attachments:
            return

        game_name = message.channel.name if hasattr(message.channel, "name") else "Unknown Thread"
        msg_url = self._build_message_link_from_msg(message)
        
        log.info(f"[UEVR Webhooks] Detected new profile archive in #{game_name} by {message.author}. Triggering webhooks.")

        for attachment in valid_attachments:
            payload = {
                "event": "new_uevr_profile",
                "game": game_name,
                "author": str(message.author),
                "author_id": message.author.id,
                "filename": attachment.filename,
                "content": message.content,
                "message_url": msg_url,
                "download_url": attachment.url,
                "timestamp": datetime.utcnow().timestamp()
            }
            
            # Dispatch
            await asyncio.gather(
                self.trigger_discord(payload),
                self.trigger_hass(payload),
                self.trigger_github(payload)
            )

    async def trigger_discord(self, payload: dict):
        hooks = await self.config.discord_webhooks()
        if not hooks: return

        embed = discord.Embed(
            title=f"New UEVR Profile: {payload['game']}",
            description=f"A new profile archive was uploaded by **{payload['author']}**:\n`{payload['filename']}`\n\n[Jump to Message]({payload['message_url']})",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        if payload['content']:
            embed.add_field(name="Message", value=payload['content'][:1024], inline=False)
            
        for webhook_url in hooks:
            try:
                # Basic aiohttp dispatch to Discord Webhook
                json_data = {"embeds": [embed.to_dict()]}
                async with self.session.post(webhook_url, json=json_data) as resp:
                    if resp.status >= 400:
                        log.warning(f"[UEVR Webhooks] Discord webhook returned error: {resp.status}")
            except Exception as e:
                log.error(f"[UEVR Webhooks] Failed to trigger Discord webhook: {e}")

    async def trigger_hass(self, payload: dict):
        hooks = await self.config.hass_webhooks()
        if not hooks: return
        
        for webhook_url in hooks:
            try:
                async with self.session.post(webhook_url, json=payload) as resp:
                    if resp.status >= 400:
                        log.warning(f"[UEVR Webhooks] Home Assistant webhook returned error: {resp.status}")
            except Exception as e:
                log.error(f"[UEVR Webhooks] Failed to trigger Home Assistant webhook: {e}")

    async def trigger_github(self, payload: dict):
        hooks = await self.config.github_webhooks()
        token = await self.config.github_token()
        if not hooks or not token: return
        
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "Authorization": f"Bearer {token}"
        }
        
        # GitHub repository dispatch format
        github_payload = {
            "event_type": "new_uevr_profile",
            "client_payload": payload
        }

        for webhook_url in hooks:
            if not webhook_url: continue
            try:
                async with self.session.post(webhook_url, headers=headers, json=github_payload) as resp:
                    if resp.status >= 400:
                        log.warning(f"[UEVR Webhooks] GitHub webhook returned error: {resp.status}")
            except Exception as e:
                log.error(f"[UEVR Webhooks] Failed to trigger GitHub webhook: {e}")
