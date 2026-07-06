"""Status Monitor cog for Red-DiscordBot.

Polls https://lookup.minopia.de/api/status/all and logs every status change
for every monitored service to configured channels. No filtering is applied.
"""

from typing import Any, ClassVar, Dict, List, Optional
from datetime import datetime, timezone
from logging import getLogger
import asyncio

import aiohttp
import discord
from discord.ext import tasks
from redbot.core import Config, checks, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import error, info, success

from .pcx_lib import reply

log = getLogger("red.blu.statusmonitor")

API_URL = "https://lookup.minopia.de/api/status/all"


class StatusMonitorCog(commands.Cog):
    """Monitor service statuses from lookup.minopia.de and log all changes to channels."""

    __author__ = "Bluscream"
    __version__ = "1.0.0"

    default_global_settings: ClassVar[Dict[str, Any]] = {
        "schema_version": 1,
        "check_interval": 900,  # 15 minutes
        "last_snapshot": {},  # service_id -> {status, indicator, operational, active_incidents}
        "last_incidents": {},  # incident_key -> {status, impact, name, ...}
        "api_online": True,  # whether the last fetch to the lookup API succeeded
    }

    default_guild_settings: ClassVar[Dict[str, Any]] = {
        "channels": [],  # list of channel IDs
    }

    # Fields whose change counts as a "status change" for a service.
    TRACKED_FIELDS: ClassVar[List[str]] = [
        "status",
        "indicator",
        "operational",
        "active_incidents",
    ]

    def __init__(self, bot: Red) -> None:
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=1884366862, force_registration=True
        )
        self.config.register_global(**self.default_global_settings)
        self.config.register_guild(**self.default_guild_settings)

        self._session: Optional[aiohttp.ClientSession] = None
        self._task_started = False

    #
    # Red methods
    #

    def format_help_for_context(self, ctx: commands.Context) -> str:
        pre_processed = super().format_help_for_context(ctx)
        return f"{pre_processed}\n\nCog Version: {self.__version__}"

    async def red_delete_data_for_user(self, *, _requester: str, _user_id: int) -> None:
        return

    #
    # Initialization
    #

    async def initialize(self) -> None:
        """Perform setup actions before loading cog."""
        self._session = aiohttp.ClientSession()
        interval = await self.config.check_interval()
        self.status_check_loop.change_interval(seconds=interval)
        if not self._task_started:
            self.status_check_loop.start()
            self._task_started = True

    def cog_unload(self) -> None:
        self.status_check_loop.cancel()
        if self._session:
            asyncio.create_task(self._session.close())

    #
    # Fetching
    #

    async def _fetch_status(self) -> Optional[Dict[str, Any]]:
        """Fetch and return the parsed API payload, or None on failure."""
        if not self._session:
            self._session = aiohttp.ClientSession()
        try:
            async with self._session.get(
                API_URL, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status != 200:
                    log.warning("Status API returned HTTP %s", resp.status)
                    return None
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            log.warning("Failed to fetch status API: %s", e)
            return None
        except Exception as e:  # noqa: BLE001
            log.error("Unexpected error fetching status API: %s", e, exc_info=True)
            return None

    @staticmethod
    def _build_snapshot(data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """Reduce the API payload to a per-service snapshot of tracked fields."""
        snapshot: Dict[str, Dict[str, Any]] = {}
        services = (data.get("response") or {}).get("services") or []
        for svc in services:
            service_id = svc.get("service") or svc.get("name")
            if not service_id:
                continue
            snapshot[str(service_id)] = {
                "name": svc.get("name", service_id),
                "status": svc.get("status"),
                "indicator": svc.get("indicator"),
                "operational": svc.get("operational"),
                "active_incidents": svc.get("active_incidents"),
                "page_url": svc.get("page_url"),
                "icon": svc.get("icon"),
                "category": svc.get("category"),
            }
        return snapshot

    @staticmethod
    def _incident_key(inc: Dict[str, Any]) -> str:
        """Build a stable key for an incident."""
        return inc.get("url") or f"{inc.get('service')}:{inc.get('name')}"

    @classmethod
    def _build_incidents(cls, data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """Reduce the API payload to a per-incident snapshot keyed by a stable id."""
        incidents: Dict[str, Dict[str, Any]] = {}
        for inc in (data.get("response") or {}).get("incidents") or []:
            key = cls._incident_key(inc)
            if not key:
                continue
            incidents[key] = {
                "service": inc.get("service"),
                "name": inc.get("name"),
                "impact": inc.get("impact"),
                "status": inc.get("status"),
                "url": inc.get("url"),
            }
        return incidents

    INCIDENT_FIELDS: ClassVar[List[str]] = ["status", "impact", "name"]

    def _diff_incidents(
        self,
        old: Dict[str, Dict[str, Any]],
        new: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Return a list of incident change descriptors between two snapshots."""
        changes: List[Dict[str, Any]] = []

        for key, new_inc in new.items():
            old_inc = old.get(key)
            if old_inc is None:
                changes.append(
                    {"type": "incident_new", "incident": new_inc, "before": None, "fields": []}
                )
                continue
            changed_fields = [
                field
                for field in self.INCIDENT_FIELDS
                if old_inc.get(field) != new_inc.get(field)
            ]
            if changed_fields:
                changes.append(
                    {
                        "type": "incident_update",
                        "incident": new_inc,
                        "before": old_inc,
                        "fields": changed_fields,
                    }
                )

        for key, old_inc in old.items():
            if key not in new:
                changes.append(
                    {"type": "incident_resolved", "incident": old_inc, "before": old_inc, "fields": []}
                )

        return changes

    def _diff_snapshots(
        self,
        old: Dict[str, Dict[str, Any]],
        new: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Return a list of change descriptors between two snapshots."""
        changes: List[Dict[str, Any]] = []

        for service_id, new_svc in new.items():
            old_svc = old.get(service_id)
            if old_svc is None:
                # Newly appearing service - only report if there's a prior snapshot at all.
                if old:
                    changes.append(
                        {"type": "added", "service": new_svc, "before": None, "fields": []}
                    )
                continue

            changed_fields = [
                field
                for field in self.TRACKED_FIELDS
                if old_svc.get(field) != new_svc.get(field)
            ]
            if changed_fields:
                changes.append(
                    {
                        "type": "changed",
                        "service": new_svc,
                        "before": old_svc,
                        "fields": changed_fields,
                    }
                )

        # Services that disappeared from the API.
        for service_id, old_svc in old.items():
            if service_id not in new:
                changes.append(
                    {"type": "removed", "service": old_svc, "before": old_svc, "fields": []}
                )

        return changes

    #
    # Background task
    #

    @tasks.loop(seconds=900)
    async def status_check_loop(self) -> None:
        try:
            data = await self._fetch_status()
            if not data:
                await self._set_api_online(False)
                return
            await self._set_api_online(True)

            new_snapshot = self._build_snapshot(data)
            if not new_snapshot:
                return

            old_snapshot = await self.config.last_snapshot()
            changes = self._diff_snapshots(old_snapshot, new_snapshot)

            new_incidents = self._build_incidents(data)
            old_incidents = await self.config.last_incidents()
            changes += self._diff_incidents(old_incidents, new_incidents)

            # Always persist the latest snapshots.
            await self.config.last_snapshot.set(new_snapshot)
            await self.config.last_incidents.set(new_incidents)

            if changes:
                await self._post_changes(changes)
        except Exception as e:  # noqa: BLE001
            log.error("Error in status check loop: %s", e, exc_info=True)

    @status_check_loop.before_loop
    async def before_status_check_loop(self) -> None:
        await self.bot.wait_until_ready()
        # Populate the initial snapshot so the first real poll doesn't report
        # every service as a change.
        if not await self.config.last_snapshot():
            data = await self._fetch_status()
            if data:
                snapshot = self._build_snapshot(data)
                if snapshot:
                    await self.config.last_snapshot.set(snapshot)
                    await self.config.last_incidents.set(self._build_incidents(data))

    #
    # Posting
    #

    def _change_embed(self, change: Dict[str, Any]) -> discord.Embed:
        if change["type"].startswith("incident_"):
            return self._incident_embed(change)

        svc = change["service"]
        name = svc.get("name", "Unknown")
        operational = svc.get("operational")

        if change["type"] == "added":
            color = discord.Color.blurple()
            title = f"🆕 {name} is now being monitored"
        elif change["type"] == "removed":
            color = discord.Color.light_grey()
            title = f"➖ {name} is no longer being monitored"
        elif operational is True:
            color = discord.Color.green()
            title = f"✅ {name} status changed"
        elif operational is False:
            color = discord.Color.red()
            title = f"⚠️ {name} status changed"
        else:
            color = discord.Color.orange()
            title = f"🔔 {name} status changed"

        embed = discord.Embed(
            title=title,
            color=color,
            timestamp=datetime.now(timezone.utc),
        )
        if svc.get("icon"):
            embed.set_thumbnail(url=svc["icon"])
        if svc.get("page_url"):
            embed.url = svc["page_url"]
        if svc.get("category"):
            embed.set_footer(text=f"Category: {svc['category']}")

        if svc.get("status"):
            embed.description = str(svc["status"])

        before = change.get("before")
        if change["type"] == "changed" and before:
            for field in change["fields"]:
                old_val = before.get(field)
                new_val = svc.get(field)
                embed.add_field(
                    name=field.replace("_", " ").title(),
                    value=f"`{old_val}` → `{new_val}`",
                    inline=True,
                )

        return embed

    def _incident_embed(self, change: Dict[str, Any]) -> discord.Embed:
        inc = change["incident"]
        name = inc.get("name", "Unknown incident")
        service = inc.get("service", "")

        if change["type"] == "incident_new":
            color = discord.Color.red()
            title = f"🚨 New incident: {name}"
        elif change["type"] == "incident_resolved":
            color = discord.Color.green()
            title = f"✅ Incident resolved: {name}"
        else:
            color = discord.Color.orange()
            title = f"🔧 Incident updated: {name}"

        embed = discord.Embed(
            title=title,
            color=color,
            timestamp=datetime.now(timezone.utc),
        )
        if inc.get("url"):
            embed.url = inc["url"]

        parts = []
        if service:
            parts.append(f"Service: **{service}**")
        if inc.get("impact"):
            parts.append(f"Impact: **{inc['impact']}**")
        if inc.get("status"):
            parts.append(f"Status: **{inc['status']}**")
        embed.description = "\n".join(parts) or None

        before = change.get("before")
        if change["type"] == "incident_update" and before:
            for field in change["fields"]:
                embed.add_field(
                    name=field.title(),
                    value=f"`{before.get(field)}` → `{inc.get(field)}`",
                    inline=True,
                )

        embed.set_footer(text="Service Incident")
        return embed

    async def _post_changes(self, changes: List[Dict[str, Any]]) -> None:
        """Post all change embeds to every configured channel across all guilds."""
        for change in changes:
            await self._broadcast(self._change_embed(change))

    async def _set_api_online(self, online: bool) -> None:
        """Track lookup-API reachability and announce transitions to channels."""
        was_online = await self.config.api_online()
        if was_online == online:
            return
        await self.config.api_online.set(online)

        if online:
            embed = discord.Embed(
                title="🟢 Lookup API connection restored",
                description=f"Successfully reconnected to the status lookup API.\n{API_URL}",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc),
            )
            log.info("Lookup API connection restored.")
        else:
            embed = discord.Embed(
                title="🔴 Lookup API connection lost",
                description=(
                    "Unable to reach the status lookup API. Service status "
                    f"updates are paused until it recovers.\n{API_URL}"
                ),
                color=discord.Color.dark_red(),
                timestamp=datetime.now(timezone.utc),
            )
            log.warning("Lookup API connection lost.")

        embed.set_footer(text="Status Monitor")
        await self._broadcast(embed)

    async def _broadcast(self, embed: discord.Embed) -> None:
        """Send a single embed to every configured channel across all guilds."""
        for guild in self.bot.guilds:
            channel_ids = await self.config.guild(guild).channels()
            if not channel_ids:
                continue
            for channel_id in channel_ids:
                channel = guild.get_channel(int(channel_id))
                if not channel or not isinstance(channel, discord.TextChannel):
                    continue
                if not channel.permissions_for(guild.me).send_messages:
                    continue
                try:
                    await channel.send(embed=embed)
                except discord.HTTPException as e:
                    log.error(
                        "Failed to send message to channel %s: %s", channel_id, e
                    )

    #
    # Commands
    #

    @commands.group(name="statusmonitor", aliases=["statusmon"])
    async def statusmonitor_group(self, ctx: commands.Context) -> None:
        """Service status monitoring commands."""
        pass

    @statusmonitor_group.command(name="addchannel")
    @checks.admin_or_permissions(manage_guild=True)
    async def add_channel(
        self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None
    ) -> None:
        """Add a channel to receive status change updates.

        If no channel is specified, uses the current channel.
        """
        if not ctx.guild:
            await reply(ctx, error("This command can only be used in a server."))
            return

        target = channel or ctx.channel
        if not isinstance(target, discord.TextChannel):
            await reply(ctx, error("Please specify a valid text channel."))
            return

        async with self.config.guild(ctx.guild).channels() as channels:
            if target.id in channels:
                await reply(
                    ctx, info(f"{target.mention} is already receiving status updates.")
                )
                return
            channels.append(target.id)
        await reply(
            ctx, success(f"Added {target.mention} to receive status change updates.")
        )

    @statusmonitor_group.command(name="removechannel")
    @checks.admin_or_permissions(manage_guild=True)
    async def remove_channel(
        self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None
    ) -> None:
        """Remove a channel from receiving status change updates.

        If no channel is specified, uses the current channel.
        """
        if not ctx.guild:
            await reply(ctx, error("This command can only be used in a server."))
            return

        target = channel or ctx.channel
        if not isinstance(target, discord.TextChannel):
            await reply(ctx, error("Please specify a valid text channel."))
            return

        async with self.config.guild(ctx.guild).channels() as channels:
            if target.id not in channels:
                await reply(
                    ctx, info(f"{target.mention} is not receiving status updates.")
                )
                return
            channels.remove(target.id)
        await reply(ctx, success(f"Removed {target.mention} from status updates."))

    @statusmonitor_group.command(name="channels")
    async def list_channels(self, ctx: commands.Context) -> None:
        """List channels configured to receive status change updates."""
        if not ctx.guild:
            await reply(ctx, error("This command can only be used in a server."))
            return

        channel_ids = await self.config.guild(ctx.guild).channels()
        if not channel_ids:
            await reply(ctx, info("No channels are configured in this server."))
            return

        lines = []
        for channel_id in channel_ids:
            channel = ctx.guild.get_channel(int(channel_id))
            lines.append(
                f"• {channel.mention}" if channel else f"• Unknown channel (ID: {channel_id})"
            )

        embed = discord.Embed(
            title=f"Status Update Channels - {ctx.guild.name}",
            description="\n".join(lines),
            color=discord.Color.blue(),
        )
        await reply(ctx, embed=embed)

    @statusmonitor_group.command(name="check")
    async def check_status(self, ctx: commands.Context) -> None:
        """Show the current status of all monitored services."""
        async with ctx.typing():
            data = await self._fetch_status()
            if not data:
                await reply(ctx, error("Failed to fetch status from the API."))
                return

            snapshot = self._build_snapshot(data)
            if not snapshot:
                await reply(ctx, info("No services returned by the API."))
                return

            down = [s for s in snapshot.values() if s.get("operational") is False]
            embed = discord.Embed(
                title="Service Status",
                color=discord.Color.red() if down else discord.Color.green(),
                timestamp=datetime.now(timezone.utc),
            )
            lines = []
            for svc in sorted(snapshot.values(), key=lambda s: str(s.get("name"))):
                icon = "🔴" if svc.get("operational") is False else "🟢"
                lines.append(f"{icon} **{svc.get('name')}** — {svc.get('status')}")
            description = "\n".join(lines)
            if len(description) > 4000:
                description = description[:3997] + "..."
            embed.description = description
            incident_count = len(self._build_incidents(data))
            embed.set_footer(
                text=f"{len(down)} service(s) with issues • {incident_count} active incident(s)"
            )
            await reply(ctx, embed=embed)

    @statusmonitor_group.command(name="interval")
    @checks.admin_or_permissions(manage_guild=True)
    async def interval_command(
        self, ctx: commands.Context, seconds: Optional[int] = None
    ) -> None:
        """Get or set the check interval in seconds (minimum 60).

        Only bot owners can change the interval, as it is a global setting.
        """
        if seconds is None:
            interval = await self.config.check_interval()
            await reply(
                ctx,
                info(f"Current check interval: {interval} seconds ({interval // 60} minutes)."),
            )
            return

        if not await self.bot.is_owner(ctx.author):
            await reply(ctx, error("Only the bot owner can change the check interval."))
            return

        if seconds < 60:
            await reply(ctx, error("Interval must be at least 60 seconds."))
            return

        await self.config.check_interval.set(seconds)
        self.status_check_loop.change_interval(seconds=seconds)
        await reply(
            ctx,
            success(f"Check interval set to {seconds} seconds ({seconds // 60} minutes)."),
        )
