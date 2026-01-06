"""InWhitelist cog for Red-DiscordBot"""

from typing import ClassVar, Dict, Optional
from logging import getLogger
import re

import discord
import aiohttp
from redbot.core import Config, checks, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import error, info, success, warning, box

from .pcx_lib import checkmark
from .automod_compat import (
    get_automod_enums,
    get_automod_classes,
    AutoModRuleEventType as CompatEventType,
    AutoModRuleTriggerType as CompatTriggerType,
    AutoModRuleActionType as CompatActionType
)

log = getLogger("red.blu.inwhitelist")

# Try to use native discord.py AutoMod enums, fall back to compatibility layer
AutoModEventType, AutoModTriggerType, AutoModActionType, HAS_NATIVE_ENUMS = get_automod_enums()
AutoModAction, AutoModActionMetadata, AutoModTriggerMetadata, HAS_NATIVE_CLASSES = get_automod_classes()

if not HAS_NATIVE_ENUMS:
    log.info("Using compatibility AutoMod enums (discord.py version doesn't have native support)")
if not HAS_NATIVE_CLASSES:
    log.info("Using compatibility AutoMod classes (discord.py version doesn't have native support)")

# Regex patterns for detecting Discord invites
INVITE_PATTERNS = [
    r"(https?://(www\.)?)?discord\.gg/[a-zA-Z0-9]{7,10}",
    r"(https?://((www\.)?)?(discordapp\.com|ptb\.discordapp\.com|canary\.discordapp\.com)/invite/[a-zA-Z0-9]{7,10})"
]

# Default rule configuration
DEFAULT_RULE_NAME = "Generated Discord invites"
DEFAULT_RULE_CONFIG = {
    "name": DEFAULT_RULE_NAME,
    "event_type": 1,  # Message sent
    "trigger_type": 1,  # Keyword filter
    "enabled": True,
    "actions": [
        {
            "type": 1,  # Block message
            "metadata": {
                "custom_message": "You are only permitted to send certain discord invites on this server, if you think this invite should be whitelisted, please notify a staff member!"
            }
        },
        {
            "type": 2,  # Send alert
            "metadata": {
                "channel_id": None  # Will be set to first available channel
            }
        }
    ],
    "trigger_metadata": {
        "keyword_filter": [],
        "regex_patterns": INVITE_PATTERNS,
        "allow_list": []
    },
    "exempt_roles": [],
    "exempt_channels": []
}


class InWhitelist(commands.Cog):
    """Manage Discord invite whitelists in AutoMod rules."""

    __author__ = "Bluscream"
    __version__ = "1.0.0"

    default_guild_settings: ClassVar[Dict] = {
        "schema_version": 1,
        "automod_rule_id": None,
        "invite_cache": {}  # {invite_code: {"server_name": str, "server_id": str}}
    }

    def __init__(self, bot: Red) -> None:
        """Set up the cog."""
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=1884366864, force_registration=True
        )
        self.config.register_guild(**self.default_guild_settings)

    def format_help_for_context(self, ctx: commands.Context) -> str:
        """Show version in help."""
        pre_processed = super().format_help_for_context(ctx)
        return f"{pre_processed}\n\nCog Version: {self.__version__}"

    async def red_delete_data_for_user(self, *, _requester: str, _user_id: int) -> None:
        """No user data is stored."""
        return

    async def initialize(self) -> None:
        """Perform setup actions before loading cog."""
        await self._migrate_config()

    async def _migrate_config(self) -> None:
        """Perform some configuration migrations."""
        # Future migrations can be added here
        pass

    async def resolve_invite(self, invite_code: str) -> Optional[Dict]:
        """Resolve an invite code to get server information."""
        try:
            invite = await self.bot.fetch_invite(invite_code)
            return {
                "server_name": invite.guild.name if invite.guild else "Unknown Server",
                "server_id": str(invite.guild.id) if invite.guild else None
            }
        except discord.NotFound:
            log.warning(f"Invite {invite_code} not found")
            return None
        except discord.HTTPException as e:
            log.error(f"Error resolving invite {invite_code}: {e}")
            return None

    async def cache_invite(self, guild_id: int, invite_code: str) -> Optional[Dict]:
        """Cache invite information."""
        guild_config = self.config.guild_from_id(guild_id)
        
        # Check if already cached
        invite_cache = await guild_config.invite_cache()
        if invite_code in invite_cache:
            return invite_cache[invite_code]
        
        # Resolve and cache
        invite_info = await self.resolve_invite(invite_code)
        if invite_info:
            async with guild_config.invite_cache() as cache:
                cache[invite_code] = invite_info
            return invite_info
        
        return None

    def extract_invite_code(self, invite_str: str) -> Optional[str]:
        """Extract invite code from various invite formats."""
        # Try to extract from URL patterns
        patterns = [
            r"discord\.gg/([a-zA-Z0-9]{7,10})",
            r"discord(?:app)?\.com/invite/([a-zA-Z0-9]{7,10})",
            r"^([a-zA-Z0-9]{7,10})$"  # Just the code
        ]
        
        for pattern in patterns:
            match = re.search(pattern, invite_str, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return None

    async def get_automod_rules(self, guild: discord.Guild) -> list:
        """Get all automod rules for a guild."""
        try:
            rules = await guild.fetch_automod_rules()
            return list(rules)
        except discord.Forbidden:
            log.error(f"No permission to fetch automod rules in {guild.name}")
            return []
        except discord.HTTPException as e:
            log.error(f"Error fetching automod rules in {guild.name}: {e}")
            return []

    async def find_invite_rule(self, guild: discord.Guild) -> Optional[discord.AutoModRule]:
        """Find the invite whitelist rule."""
        guild_config = self.config.guild(guild)
        rule_id = await guild_config.automod_rule_id()
        
        # Try to fetch by stored ID first
        if rule_id:
            try:
                rule = await guild.fetch_automod_rule(rule_id)
                if rule and rule.name == DEFAULT_RULE_NAME:
                    return rule
            except (discord.NotFound, discord.HTTPException):
                # Rule was deleted, clear the stored ID
                await guild_config.automod_rule_id.set(None)
        
        # Search by name
        rules = await self.get_automod_rules(guild)
        for rule in rules:
            if rule.name == DEFAULT_RULE_NAME:
                # Cache the rule ID
                await guild_config.automod_rule_id.set(rule.id)
                return rule
        
        return None

    async def ensure_automod_enabled(self, guild: discord.Guild) -> bool:
        """Ensure AutoMod is enabled for the guild."""
        # AutoMod is automatically enabled when you create a rule
        # Just check if we have permission to manage it
        if not guild.me.guild_permissions.manage_guild:
            return False
        return True

    async def create_invite_rule(self, guild: discord.Guild, initial_invite: Optional[str] = None) -> discord.AutoModRule:
        """Create the invite whitelist AutoMod rule."""
        # Get first text channel for alerts
        alert_channel = None
        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).send_messages:
                alert_channel = channel
                break
        
        if not alert_channel:
            raise ValueError("No suitable channel found for AutoMod alerts")
        
        # Prepare rule configuration
        rule_config = DEFAULT_RULE_CONFIG.copy()
        rule_config["actions"][1]["metadata"]["channel_id"] = str(alert_channel.id)
        
        # Add initial invite to allow list if provided
        if initial_invite:
            invite_code = self.extract_invite_code(initial_invite)
            if invite_code:
                rule_config["trigger_metadata"]["allow_list"] = [f"*{invite_code}*"]
        
        # Create the rule
        try:
            # Build actions list
            actions = []
            for action in rule_config["actions"]:
                action_metadata = None
                if action["metadata"]:
                    channel_id = action["metadata"].get("channel_id")
                    action_metadata = discord.AutoModActionMetadata(
                        channel_id=int(channel_id) if channel_id else None,
                        custom_message=action["metadata"].get("custom_message")
                    )
                
                # Create action with proper types
                action_type = AutoModActionType(action["type"])
                
                actions.append(AutoModAction(
                    type=action_type,
                    metadata=action_metadata
                ))
            
            # Create event and trigger types
            event_type = AutoModEventType(rule_config["event_type"])
            trigger_type = AutoModTriggerType(rule_config["trigger_type"])
            
            rule = await guild.create_automod_rule(
                name=rule_config["name"],
                event_type=event_type,
                trigger_type=trigger_type,
                trigger_metadata=AutoModTriggerMetadata(
                    keyword_filter=rule_config["trigger_metadata"]["keyword_filter"],
                    regex_patterns=rule_config["trigger_metadata"]["regex_patterns"],
                    allow_list=rule_config["trigger_metadata"]["allow_list"]
                ),
                actions=actions,
                enabled=rule_config["enabled"],
                exempt_roles=rule_config["exempt_roles"],
                exempt_channels=rule_config["exempt_channels"],
                reason="Created by InWhitelist cog"
            )
            
            # Cache the rule ID
            guild_config = self.config.guild(guild)
            await guild_config.automod_rule_id.set(rule.id)
            
            return rule
        except discord.Forbidden:
            raise ValueError("Bot lacks permission to create AutoMod rules")
        except discord.HTTPException as e:
            log.error(f"Error creating AutoMod rule: {e}")
            raise ValueError(f"Failed to create AutoMod rule: {e}")

    async def update_rule_allowlist(self, rule: discord.AutoModRule, new_allowlist: list) -> discord.AutoModRule:
        """Update the allow list of an AutoMod rule."""
        try:
            updated_rule = await rule.edit(
                trigger_metadata=AutoModTriggerMetadata(
                    keyword_filter=rule.trigger_metadata.keyword_filter or [],
                    regex_patterns=rule.trigger_metadata.regex_patterns or [],
                    allow_list=new_allowlist
                ),
                reason="Updated by InWhitelist cog"
            )
            return updated_rule
        except discord.Forbidden:
            raise ValueError("Bot lacks permission to edit AutoMod rules")
        except discord.HTTPException as e:
            log.error(f"Error updating AutoMod rule: {e}")
            raise ValueError(f"Failed to update AutoMod rule: {e}")

    @commands.group(name="invitewl", aliases=["invitewhitelist"], invoke_without_command=True)
    @checks.admin_or_permissions(manage_guild=True)
    async def invite_whitelist(self, ctx: commands.Context, invite_code: Optional[str] = None):
        """
        Manage Discord invite whitelist in AutoMod.
        
        - `!invite` - List whitelisted invites
        - `!invite <code>` - Toggle invite in whitelist
        - `!invite add <code>` - Add invite to whitelist
        - `!invite remove <code>` - Remove invite from whitelist
        """
        if ctx.invoked_subcommand is None:
            if invite_code is None:
                # Show list
                await ctx.invoke(self.invite_list)
            else:
                # Toggle invite
                await ctx.invoke(self.invite_toggle, invite_code=invite_code)

    @invite_whitelist.command(name="add")
    async def invite_add(self, ctx: commands.Context, invite_code: str):
        """
        Add an invite to the whitelist.
        
        You can provide:
        - Full invite URL (https://discord.gg/ABC123)
        - Short URL (discord.gg/ABC123)
        - Just the code (ABC123)
        """
        # Extract invite code
        code = self.extract_invite_code(invite_code)
        if not code:
            await ctx.send(error(f"Invalid invite format: {invite_code}"))
            return
        
        # Check permissions
        if not await self.ensure_automod_enabled(ctx.guild):
            await ctx.send(error("Bot lacks `Manage Server` permission to manage AutoMod rules."))
            return
        
        # Find or create rule
        rule = await self.find_invite_rule(ctx.guild)
        
        if not rule:
            # Create new rule with this invite
            try:
                rule = await self.create_invite_rule(ctx.guild, code)
                
                # Cache invite info
                invite_info = await self.cache_invite(ctx.guild.id, code)
                server_name = invite_info["server_name"] if invite_info else "Unknown Server"
                
                await ctx.send(success(
                    f"Created AutoMod rule '{DEFAULT_RULE_NAME}' and added invite `{code}` ({server_name}) to whitelist."
                ))
                await checkmark(ctx)
                return
            except ValueError as e:
                await ctx.send(error(str(e)))
                return
        
        # Check if already whitelisted
        current_allowlist = rule.trigger_metadata.allow_list or []
        wildcard_code = f"*{code}*"
        
        if any(code in item for item in current_allowlist):
            await ctx.send(warning(f"Invite `{code}` is already whitelisted."))
            return
        
        # Add to whitelist
        new_allowlist = current_allowlist + [wildcard_code]
        
        try:
            await self.update_rule_allowlist(rule, new_allowlist)
            
            # Cache invite info
            invite_info = await self.cache_invite(ctx.guild.id, code)
            server_name = invite_info["server_name"] if invite_info else "Unknown Server"
            
            await ctx.send(success(f"Added invite `{code}` ({server_name}) to whitelist."))
            await checkmark(ctx)
        except ValueError as e:
            await ctx.send(error(str(e)))

    @invite_whitelist.command(name="remove", aliases=["rm", "del", "delete"])
    async def invite_remove(self, ctx: commands.Context, invite_code: str):
        """Remove an invite from the whitelist."""
        # Extract invite code
        code = self.extract_invite_code(invite_code)
        if not code:
            await ctx.send(error(f"Invalid invite format: {invite_code}"))
            return
        
        # Find rule
        rule = await self.find_invite_rule(ctx.guild)
        if not rule:
            await ctx.send(error(f"AutoMod rule '{DEFAULT_RULE_NAME}' not found. Nothing to remove."))
            return
        
        # Check if whitelisted
        current_allowlist = rule.trigger_metadata.allow_list or []
        
        # Find matching entries
        matching_entries = [item for item in current_allowlist if code in item]
        
        if not matching_entries:
            await ctx.send(warning(f"Invite `{code}` is not in the whitelist."))
            return
        
        # Remove from whitelist
        new_allowlist = [item for item in current_allowlist if code not in item]
        
        try:
            await self.update_rule_allowlist(rule, new_allowlist)
            
            # Get cached server name
            guild_config = self.config.guild(ctx.guild)
            invite_cache = await guild_config.invite_cache()
            server_name = invite_cache.get(code, {}).get("server_name", "Unknown Server")
            
            await ctx.send(success(f"Removed invite `{code}` ({server_name}) from whitelist."))
            await checkmark(ctx)
        except ValueError as e:
            await ctx.send(error(str(e)))

    @invite_whitelist.command(name="toggle")
    async def invite_toggle(self, ctx: commands.Context, invite_code: str):
        """Toggle an invite in the whitelist (add if not present, remove if present)."""
        # Extract invite code
        code = self.extract_invite_code(invite_code)
        if not code:
            await ctx.send(error(f"Invalid invite format: {invite_code}"))
            return
        
        # Find rule
        rule = await self.find_invite_rule(ctx.guild)
        
        if not rule:
            # Create new rule with this invite
            await ctx.invoke(self.invite_add, invite_code=invite_code)
            return
        
        # Check if already whitelisted
        current_allowlist = rule.trigger_metadata.allow_list or []
        
        if any(code in item for item in current_allowlist):
            # Remove it
            await ctx.invoke(self.invite_remove, invite_code=invite_code)
        else:
            # Add it
            await ctx.invoke(self.invite_add, invite_code=invite_code)

    @invite_whitelist.command(name="list", aliases=["ls", "show"])
    async def invite_list(self, ctx: commands.Context):
        """List all whitelisted invites."""
        # Find rule
        rule = await self.find_invite_rule(ctx.guild)
        
        if not rule:
            await ctx.send(info(f"AutoMod rule '{DEFAULT_RULE_NAME}' not found. No invites are whitelisted."))
            return
        
        # Get allow list
        allowlist = rule.trigger_metadata.allow_list or []
        
        if not allowlist:
            await ctx.send(info("No invites are currently whitelisted."))
            return
        
        # Extract invite codes from wildcards
        invite_codes = []
        for item in allowlist:
            # Remove wildcards and extract code
            cleaned = item.replace("*", "").replace("/", "")
            # Extract just the invite code part
            code = self.extract_invite_code(cleaned)
            if code:
                invite_codes.append(code)
        
        # Get cached server names
        guild_config = self.config.guild(ctx.guild)
        invite_cache = await guild_config.invite_cache()
        
        # Build embed
        embed = discord.Embed(
            title=f"Whitelisted Discord Invites ({len(invite_codes)})",
            description=f"These invites are allowed in the '{DEFAULT_RULE_NAME}' AutoMod rule.",
            color=discord.Color.green()
        )
        
        # Group invites for display
        invite_list = []
        for code in invite_codes:
            cached_info = invite_cache.get(code)
            if cached_info:
                server_name = cached_info.get("server_name", "Unknown Server")
                invite_list.append(f"`{code}` - **{server_name}**")
            else:
                # Try to resolve it now
                invite_info = await self.cache_invite(ctx.guild.id, code)
                if invite_info:
                    server_name = invite_info["server_name"]
                    invite_list.append(f"`{code}` - **{server_name}**")
                else:
                    invite_list.append(f"`{code}` - *Unknown/Expired*")
        
        # Split into chunks if too many
        chunk_size = 10
        for i in range(0, len(invite_list), chunk_size):
            chunk = invite_list[i:i+chunk_size]
            field_name = f"Invites {i+1}-{min(i+chunk_size, len(invite_list))}" if len(invite_list) > chunk_size else "Invites"
            embed.add_field(
                name=field_name,
                value="\n".join(chunk),
                inline=False
            )
        
        # Add rule info
        embed.set_footer(text=f"Rule ID: {rule.id} | Status: {'✅ Enabled' if rule.enabled else '❌ Disabled'}")
        
        await ctx.send(embed=embed)

    @invite_whitelist.command(name="info")
    async def invite_info(self, ctx: commands.Context):
        """Show information about the AutoMod invite rule."""
        rule = await self.find_invite_rule(ctx.guild)
        
        if not rule:
            await ctx.send(info(f"AutoMod rule '{DEFAULT_RULE_NAME}' not found."))
            return
        
        # Build embed
        embed = discord.Embed(
            title=f"AutoMod Rule: {rule.name}",
            color=discord.Color.blue() if rule.enabled else discord.Color.red()
        )
        
        embed.add_field(name="Rule ID", value=str(rule.id), inline=True)
        embed.add_field(name="Status", value="✅ Enabled" if rule.enabled else "❌ Disabled", inline=True)
        embed.add_field(name="Creator", value=f"<@{rule.creator_id}>", inline=True)
        
        # Trigger info
        trigger_type_names = {
            AutoModTriggerType.keyword: "Keyword Filter",
            AutoModTriggerType.spam: "Spam",
            AutoModTriggerType.keyword_preset: "Keyword Preset",
            AutoModTriggerType.mention_spam: "Mention Spam"
        }
        embed.add_field(
            name="Trigger Type",
            value=trigger_type_names.get(rule.trigger_type, str(rule.trigger_type)),
            inline=True
        )
        
        # Patterns
        patterns = rule.trigger_metadata.regex_patterns or []
        if patterns:
            pattern_text = "\n".join([f"`{p[:50]}{'...' if len(p) > 50 else ''}`" for p in patterns[:3]])
            if len(patterns) > 3:
                pattern_text += f"\n*+{len(patterns) - 3} more patterns*"
            embed.add_field(name="Regex Patterns", value=pattern_text, inline=False)
        
        # Whitelist count
        allowlist = rule.trigger_metadata.allow_list or []
        embed.add_field(name="Whitelisted Invites", value=str(len(allowlist)), inline=True)
        
        # Actions
        action_types = {
            AutoModActionType.block_message: "🚫 Block Message",
            AutoModActionType.send_alert_message: "📢 Send Alert",
            AutoModActionType.timeout: "⏱️ Timeout User"
        }
        actions_text = "\n".join([action_types.get(action.type, str(action.type)) for action in rule.actions])
        embed.add_field(name="Actions", value=actions_text, inline=True)
        
        # Exemptions
        exempt_roles = len(rule.exempt_roles)
        exempt_channels = len(rule.exempt_channels)
        embed.add_field(name="Exempt Roles", value=str(exempt_roles), inline=True)
        embed.add_field(name="Exempt Channels", value=str(exempt_channels), inline=True)
        
        await ctx.send(embed=embed)

    @invite_whitelist.command(name="enable")
    async def invite_enable(self, ctx: commands.Context):
        """Enable the AutoMod invite rule."""
        rule = await self.find_invite_rule(ctx.guild)
        
        if not rule:
            await ctx.send(error(f"AutoMod rule '{DEFAULT_RULE_NAME}' not found. Use `{ctx.prefix}invite add <code>` to create it."))
            return
        
        if rule.enabled:
            await ctx.send(info("Rule is already enabled."))
            return
        
        try:
            await rule.edit(enabled=True, reason="Enabled by InWhitelist cog")
            await ctx.send(success(f"Enabled AutoMod rule '{DEFAULT_RULE_NAME}'."))
            await checkmark(ctx)
        except discord.Forbidden:
            await ctx.send(error("Bot lacks permission to edit AutoMod rules."))
        except discord.HTTPException as e:
            await ctx.send(error(f"Failed to enable rule: {e}"))

    @invite_whitelist.command(name="disable")
    async def invite_disable(self, ctx: commands.Context):
        """Disable the AutoMod invite rule."""
        rule = await self.find_invite_rule(ctx.guild)
        
        if not rule:
            await ctx.send(error(f"AutoMod rule '{DEFAULT_RULE_NAME}' not found."))
            return
        
        if not rule.enabled:
            await ctx.send(info("Rule is already disabled."))
            return
        
        try:
            await rule.edit(enabled=False, reason="Disabled by InWhitelist cog")
            await ctx.send(success(f"Disabled AutoMod rule '{DEFAULT_RULE_NAME}'."))
            await checkmark(ctx)
        except discord.Forbidden:
            await ctx.send(error("Bot lacks permission to edit AutoMod rules."))
        except discord.HTTPException as e:
            await ctx.send(error(f"Failed to disable rule: {e}"))

    @invite_whitelist.command(name="clear")
    async def invite_clear(self, ctx: commands.Context):
        """Clear all whitelisted invites."""
        rule = await self.find_invite_rule(ctx.guild)
        
        if not rule:
            await ctx.send(error(f"AutoMod rule '{DEFAULT_RULE_NAME}' not found."))
            return
        
        allowlist = rule.trigger_metadata.allow_list or []
        if not allowlist:
            await ctx.send(info("No invites to clear."))
            return
        
        # Confirmation
        await ctx.send(
            f"⚠️ **WARNING**: This will remove {len(allowlist)} whitelisted invite(s). "
            f"Type `CONFIRM CLEAR` to proceed or anything else to cancel."
        )
        
        def check(message):
            return (message.author == ctx.author and 
                   message.channel == ctx.channel)
        
        try:
            response = await self.bot.wait_for('message', check=check, timeout=30.0)
            if response.content != 'CONFIRM CLEAR':
                await ctx.send("Clear cancelled.")
                return
        except Exception:
            await ctx.send("Clear cancelled due to timeout.")
            return
        
        try:
            await self.update_rule_allowlist(rule, [])
            await ctx.send(success(f"Cleared {len(allowlist)} invite(s) from whitelist."))
            await checkmark(ctx)
        except ValueError as e:
            await ctx.send(error(str(e)))
