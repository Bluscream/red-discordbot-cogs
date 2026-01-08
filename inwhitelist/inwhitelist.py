"""InWhitelist cog for Red-DiscordBot"""

from typing import ClassVar, Dict, Optional
from logging import getLogger
import re
from datetime import datetime

import discord
import aiohttp
from redbot.core import Config, checks, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import error, info, success, warning, box

from .pcx_lib import checkmark

log = getLogger("red.blu.inwhitelist")

def _parse_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """Parse ISO datetime string back to datetime object."""
    if dt_str is None:
        return None
    try:
        return datetime.fromisoformat(dt_str)
    except (ValueError, TypeError):
        return None

def _format_invite_info(code: str, server_name: str, channel_name: str, inviter: str, 
                        uses: Optional[int], max_uses: Optional[int], temporary: Optional[bool],
                        created_at: Optional[datetime], expires_at: Optional[datetime],
                        cached_info: Optional[Dict]) -> str:
    """Format invite information for display in embed fields."""
    field_value = f"**Guild:** `{server_name}`\n"
    
    # Get channel ID for mention
    channel_id = cached_info.get("channel_id") if cached_info else None
    if channel_id:
        field_value += f"**Channel:** <#{channel_id}> (`{channel_name}`)\n"
    else:
        field_value += f"**Channel:** `{channel_name}`\n"
    
    # Get inviter ID for mention
    inviter_id = cached_info.get("inviter_id") if cached_info else None
    if inviter_id:
        field_value += f"**Inviter:** <@{inviter_id}> (`{inviter}`)\n"
    else:
        field_value += f"**Inviter:** `{inviter}`\n"
    
    # Add usage information
    if uses is not None and max_uses is not None:
        if max_uses == 0:
            field_value += f"**Uses:** `{uses} (unlimited)`\n"
        else:
            field_value += f"**Uses:** `{uses}/{max_uses}`\n"
    elif uses is not None:
        field_value += f"**Uses:** `{uses}`\n"
    
    # Add temporary status
    if temporary is not None:
        field_value += f"**Temporary:** `{'Yes' if temporary else 'No'}`\n"
    
    # Add creation date
    if created_at:
        field_value += f"**Created:** `{discord.utils.format_dt(created_at, style='R')}`\n"
    
    # Add expiration info
    if expires_at:
        if expires_at > discord.utils.utcnow():
            field_value += f"**Expires:** {discord.utils.format_dt(expires_at, style='R')}\n"
        else:
            field_value += f"**Status:** ⚠️ `Expired`\n"
    else:
        field_value += f"**Status:** ✅ `Permanent`\n"
    
    return field_value

# Import AutoMod types directly from discord.py (v2.6.3+)
# Note: discord.py uses "AutoModRule*" prefix for enums and creation classes
from discord import (
    AutoModRuleTriggerType as AutoModTriggerType,
    AutoModRuleEventType as AutoModEventType,
    AutoModRuleActionType as AutoModActionType,
    AutoModRuleAction,  # Used for creating actions
    AutoModTrigger      # Used for creating triggers
)

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
                "server_id": str(invite.guild.id) if invite.guild else None,
                "channel_name": invite.channel.name if invite.channel else "Unknown Channel",
                "channel_id": str(invite.channel.id) if invite.channel else None,
                "inviter": invite.inviter.name if invite.inviter else "Unknown",
                "inviter_id": str(invite.inviter.id) if invite.inviter else None,
                "uses": invite.uses,
                "max_uses": invite.max_uses,
                "temporary": invite.temporary,
                "created_at": invite.created_at.isoformat() if invite.created_at else None,
                "expires_at": invite.expires_at.isoformat() if invite.expires_at else None
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
                # Use */ prefix to match Discord invite URLs (discord.gg/code or /invite/code)
                rule_config["trigger_metadata"]["allow_list"] = [f"*/{invite_code}*"]
        
        # Create the rule
        try:
            # Build actions list
            actions = []
            for action in rule_config["actions"]:
                # AutoModRuleAction takes parameters directly, not via metadata object
                action_type = AutoModActionType(action["type"])
                action_kwargs = {}
                
                if action.get("metadata"):
                    metadata = action["metadata"]
                    if "channel_id" in metadata and metadata["channel_id"]:
                        action_kwargs["channel_id"] = int(metadata["channel_id"])
                    if "custom_message" in metadata and metadata["custom_message"]:
                        action_kwargs["custom_message"] = metadata["custom_message"]
                    if "duration" in metadata and metadata["duration"]:
                        action_kwargs["duration"] = metadata["duration"]
                
                # Create action based on type
                if action_type == AutoModActionType.send_alert_message:
                    actions.append(AutoModRuleAction(channel_id=action_kwargs.get("channel_id")))
                elif action_type == AutoModActionType.timeout:
                    actions.append(AutoModRuleAction(duration=action_kwargs.get("duration")))
                elif action_type == AutoModActionType.block_message:
                    custom_msg = action_kwargs.get("custom_message")
                    if custom_msg:
                        actions.append(AutoModRuleAction(custom_message=custom_msg))
                    else:
                        actions.append(AutoModRuleAction())
                else:
                    # For other action types, try to create with type parameter
                    actions.append(AutoModRuleAction(type=action_type))
            
            # Create event and trigger
            event_type = AutoModEventType(rule_config["event_type"])
            trigger = AutoModTrigger(
                type=AutoModTriggerType(rule_config["trigger_type"]),
                keyword_filter=rule_config["trigger_metadata"]["keyword_filter"],
                regex_patterns=rule_config["trigger_metadata"]["regex_patterns"],
                allow_list=rule_config["trigger_metadata"]["allow_list"]
            )
            
            rule = await guild.create_automod_rule(
                name=rule_config["name"],
                event_type=event_type,
                trigger=trigger,
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
            # Create a new trigger with updated metadata
            updated_trigger = AutoModTrigger(
                type=rule.trigger.type,
                keyword_filter=rule.trigger.keyword_filter or [],
                regex_patterns=rule.trigger.regex_patterns or [],
                allow_list=new_allowlist
            )
            updated_rule = await rule.edit(
                trigger=updated_trigger,
                reason="Updated by InWhitelist cog"
            )
            return updated_rule
        except discord.Forbidden:
            raise ValueError("Bot lacks permission to edit AutoMod rules")
        except discord.HTTPException as e:
            log.error(f"Error updating AutoMod rule: {e}")
            raise ValueError(f"Failed to update AutoMod rule: {e}")

    @commands.group(name="invitewl", aliases=["invitewhitelist","iwl"], invoke_without_command=True)
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
            await ctx.reply(error(f"{ctx.author.mention} Invalid invite format: {invite_code}"))
            return
        
        # Check permissions
        if not await self.ensure_automod_enabled(ctx.guild):
            await ctx.reply(error(f"{ctx.author.mention} Bot lacks `Manage Server` permission to manage AutoMod rules."))
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
                
                await ctx.reply(success(
                    f"{ctx.author.mention} Created AutoMod rule '{DEFAULT_RULE_NAME}' and added invite `{code}` ({server_name}) to whitelist."
                ))
                await checkmark(ctx)
                return
            except ValueError as e:
                await ctx.reply(error(str(e)))
                return
        
        # Check if already whitelisted
        current_allowlist = rule.trigger.allow_list or []
        # Use */ prefix to match Discord invite URLs (discord.gg/code or /invite/code)
        wildcard_code = f"*/{code}*"
        
        if any(code in item for item in current_allowlist):
            await ctx.reply(warning(f"{ctx.author.mention} Invite `{code}` is already whitelisted."))
            return
        
        # Add to whitelist
        new_allowlist = current_allowlist + [wildcard_code]
        
        try:
            await self.update_rule_allowlist(rule, new_allowlist)
            
            # Cache invite info
            invite_info = await self.cache_invite(ctx.guild.id, code)
            server_name = invite_info["server_name"] if invite_info else "Unknown Server"
            
            await ctx.reply(success(f"{ctx.author.mention} Added invite `{code}` ({server_name}) to whitelist."))
            await checkmark(ctx)
        except ValueError as e:
            await ctx.reply(error(f"{ctx.author.mention} {str(e)}"))

    @invite_whitelist.command(name="remove", aliases=["rm", "del", "delete"])
    async def invite_remove(self, ctx: commands.Context, invite_code: str):
        """Remove an invite from the whitelist."""
        # Extract invite code
        code = self.extract_invite_code(invite_code)
        if not code:
            await ctx.reply(error(f"{ctx.author.mention} Invalid invite format: {invite_code}"))
            return
        
        # Find rule
        rule = await self.find_invite_rule(ctx.guild)
        if not rule:
            await ctx.reply(error(f"{ctx.author.mention} AutoMod rule '{DEFAULT_RULE_NAME}' not found. Nothing to remove."))
            return
        
        # Check if whitelisted
        current_allowlist = rule.trigger.allow_list or []
        
        # Find matching entries
        matching_entries = [item for item in current_allowlist if code in item]
        
        if not matching_entries:
            await ctx.reply(warning(f"{ctx.author.mention} Invite `{code}` is not in the whitelist."))
            return
        
        # Remove from whitelist
        new_allowlist = [item for item in current_allowlist if code not in item]
        
        try:
            await self.update_rule_allowlist(rule, new_allowlist)
            
            # Get cached server name
            guild_config = self.config.guild(ctx.guild)
            invite_cache = await guild_config.invite_cache()
            server_name = invite_cache.get(code, {}).get("server_name", "Unknown Server")
            
            await ctx.reply(success(f"{ctx.author.mention} Removed invite `{code}` ({server_name}) from whitelist."))
            await checkmark(ctx)
        except ValueError as e:
            await ctx.reply(error(f"{ctx.author.mention} {str(e)}"))

    @invite_whitelist.command(name="toggle")
    async def invite_toggle(self, ctx: commands.Context, invite_code: str):
        """Toggle an invite in the whitelist (add if not present, remove if present)."""
        # Extract invite code
        code = self.extract_invite_code(invite_code)
        if not code:
            await ctx.reply(error(f"{ctx.author.mention} Invalid invite format: {invite_code}"))
            return
        
        # Find rule
        rule = await self.find_invite_rule(ctx.guild)
        
        if not rule:
            # Create new rule with this invite
            await ctx.invoke(self.invite_add, invite_code=invite_code)
            return
        
        # Check if already whitelisted
        current_allowlist = rule.trigger.allow_list or []
        
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
            await ctx.reply(info(f"{ctx.author.mention} AutoMod rule '{DEFAULT_RULE_NAME}' not found. No invites are whitelisted."))
            return
        
        # Get allow list
        allowlist = rule.trigger.allow_list or []
        
        if not allowlist:
            await ctx.reply(info(f"{ctx.author.mention} No invites are currently whitelisted."))
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
            title="",
            description=f"{len(invite_codes)} whitelisted invites in `{DEFAULT_RULE_NAME}`",
            color=discord.Color.green()
        )
        
        # Add each invite as a separate field with detailed metadata
        for i, code in enumerate(invite_codes, 1):
            # Try to get cached info first
            cached_info = invite_cache.get(code)
            
            if cached_info and len(cached_info.keys()) > 2:  # Check if we have detailed cached info
                # Use cached detailed info
                server_name = cached_info.get("server_name", "Unknown Server")
                channel_name = cached_info.get("channel_name", "Unknown Channel")
                inviter = cached_info.get("inviter", "Unknown")
                uses = cached_info.get("uses")
                max_uses = cached_info.get("max_uses")
                temporary = cached_info.get("temporary", False)
                created_at = _parse_datetime(cached_info.get("created_at"))
                expires_at = _parse_datetime(cached_info.get("expires_at"))
            else:
                # Try to resolve fresh invite info
                invite_info = await self.resolve_invite(code)
                if invite_info:
                    # Cache the detailed info
                    async with guild_config.invite_cache() as cache:
                        cache[code] = invite_info
                    
                    server_name = invite_info["server_name"]
                    channel_name = invite_info["channel_name"]
                    inviter = invite_info["inviter"]
                    uses = invite_info["uses"]
                    max_uses = invite_info["max_uses"]
                    temporary = invite_info["temporary"]
                    created_at = _parse_datetime(invite_info["created_at"])
                    expires_at = _parse_datetime(invite_info["expires_at"])
                else:
                    # Use basic cached info or show as expired
                    if cached_info:
                        server_name = cached_info.get("server_name", "Unknown Server")
                    else:
                        server_name = "Unknown/Expired"
                    channel_name = "Unknown"
                    inviter = "Unknown"
                    uses = None
                    max_uses = None
                    temporary = None
                    created_at = None
                    expires_at = None
            
            # Build field value with detailed metadata using helper function
            field_value = _format_invite_info(
                code=code,
                server_name=server_name,
                channel_name=channel_name,
                inviter=inviter,
                uses=uses,
                max_uses=max_uses,
                temporary=temporary,
                created_at=created_at,
                expires_at=expires_at,
                cached_info=cached_info
            )
            
            # Add field (limit to 25 fields total)
            if i <= 25:
                embed.add_field(
                    name=f"https://discord.gg/{code}",
                    value=field_value,
                    inline=False
                )
            else:
                # If we have more than 25 invites, add a note
                if i == 26:
                    embed.add_field(
                        name="⚠️ Field Limit Reached",
                        value=f"Showing first 25 invites. {len(invite_codes) - 25} more invites not shown due to Discord embed limits.",
                        inline=False
                    )
                break
        
        # Add rule info
        embed.set_footer(text=f"{'✅' if rule.enabled else '❌'} {rule.id}")
        
        await ctx.reply(embed=embed)

    @invite_whitelist.command(name="info")
    async def invite_info(self, ctx: commands.Context):
        """Show information about the AutoMod invite rule."""
        rule = await self.find_invite_rule(ctx.guild)
        
        if not rule:
            await ctx.reply(info(f"{ctx.author.mention} AutoMod rule '{DEFAULT_RULE_NAME}' not found."))
            return
        
        # Build embed
        embed = discord.Embed(
            title=f"AutoMod Rule: {rule.name}",
            color=discord.Color.blue() if rule.enabled else discord.Color.red()
        )
        
        embed.add_field(name="Rule ID", value=str(rule.id), inline=True)
        embed.add_field(name="Status", value="✅ Enabled" if rule.enabled else "❌ Disabled", inline=True)
        embed.add_field(name="Creator", value=f"<@{rule.creator_id}>", inline=True)
        
        # Trigger info - use integer values for compatibility
        trigger_type_value = rule.trigger.type.value if hasattr(rule.trigger.type, 'value') else rule.trigger.type
        trigger_type_names = {
            1: "Keyword Filter",        # keyword
            2: "Harmful Link",          # deprecated
            3: "Spam",                  # spam
            4: "Keyword Preset",        # keyword_preset
            5: "Mention Spam",          # mention_spam
            6: "Member Profile"         # member_profile
        }
        embed.add_field(
            name="Trigger Type",
            value=trigger_type_names.get(trigger_type_value, f"Unknown ({trigger_type_value})"),
            inline=True
        )
        
        # Patterns
        patterns = rule.trigger.regex_patterns or []
        if patterns:
            pattern_text = "\n".join([f"`{p[:50]}{'...' if len(p) > 50 else ''}`" for p in patterns[:3]])
            if len(patterns) > 3:
                pattern_text += f"\n*+{len(patterns) - 3} more patterns*"
            embed.add_field(name="Regex Patterns", value=pattern_text, inline=False)
        
        # Whitelisted Invites
        allowlist = rule.trigger.allow_list or []
        if allowlist:
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
            
            # Build invite list
            invite_list = []
            for code in invite_codes:
                cached_info = invite_cache.get(code)
                template = "discord.gg/{code}: `{name}`"
                if cached_info:
                    server_name = cached_info.get("server_name", "Unknown Server")
                    invite_list.append(template.format(code=code, name=server_name))
                else:
                    # Try to resolve it now
                    invite_info = await self.cache_invite(ctx.guild.id, code)
                    if invite_info:
                        server_name = invite_info["server_name"]
                        invite_list.append(template.format(code=code, name=server_name))
                    else:
                        invite_list.append(f"`{code}` - *Unknown/Expired*")
            
            # Limit display to prevent embed overflow
            if len(invite_list) > 10:
                invite_text = "\n".join(invite_list[:10]) + f"\n*+{len(invite_list) - 10} more*"
            else:
                invite_text = "\n".join(invite_list) if invite_list else "None"
            
            embed.add_field(name=f"{len(invite_codes)} Whitelisted Invites", value=invite_text, inline=False)
        else:
            embed.add_field(name="0 Whitelisted Invites", value="None", inline=False)
        
        # Actions - use integer values for compatibility
        action_type_names = {
            1: "🚫 Block Message",           # block_message
            2: "📢 Send Alert",              # send_alert_message
            3: "⏱️ Timeout User",            # timeout
            4: "🚷 Block Interactions"       # block_member_interactions
        }
        action_values = []
        for action in rule.actions:
            action_value = action.type.value if hasattr(action.type, 'value') else action.type
            action_values.append(action_type_names.get(action_value, f"Unknown ({action_value})"))
        actions_text = "\n".join(action_values)
        embed.add_field(name="Actions", value=actions_text, inline=True)
        
        # Exemptions
        # Exempt Roles - Try both object and ID properties
        exempt_roles_data = getattr(rule, 'exempt_roles', None) or getattr(rule, 'exempt_role_ids', None)
        if exempt_roles_data:
            role_names = []
            for role_data in exempt_roles_data:
                # If it's already a Role object
                if hasattr(role_data, 'id') and hasattr(role_data, 'name'):
                    role_names.append(f"<@&{role_data.id}> ({role_data.name})")
                # If it's an ID (int or string)
                else:
                    role_id = role_data
                    if isinstance(role_id, str):
                        try:
                            role_id = int(role_id)
                        except ValueError:
                            role_names.append(f"@{role_id} (invalid)")
                            continue
                    
                    role = ctx.guild.get_role(role_id)
                    if role:
                        role_names.append(f"<@&{role_id}> ({role.name})")
                    else:
                        role_names.append(f"<@&{role_id}> (deleted)")
            
            # Limit display to prevent embed overflow
            if len(role_names) > 10:
                roles_text = "\n".join(role_names[:10]) + f"\n*+{len(role_names) - 10} more*"
            else:
                roles_text = "\n".join(role_names)
            
            embed.add_field(name=f"{len(exempt_roles_data)} Exempt Roles", value=roles_text, inline=False)
        else:
            embed.add_field(name="0 Exempt Roles", value="None", inline=False)
        
        # Exempt Channels - Try both object and ID properties
        exempt_channels_data = getattr(rule, 'exempt_channels', None) or getattr(rule, 'exempt_channel_ids', None)
        if exempt_channels_data:
            channel_names = []
            for channel_data in exempt_channels_data:
                # If it's already a Channel object
                if hasattr(channel_data, 'id') and hasattr(channel_data, 'name'):
                    channel_names.append(f"<#{channel_data.id}> ({channel_data.name})")
                # If it's an ID (int or string)
                else:
                    channel_id = channel_data
                    if isinstance(channel_id, str):
                        try:
                            channel_id = int(channel_id)
                        except ValueError:
                            channel_names.append(f"#{channel_id} (invalid)")
                            continue
                    
                    channel = ctx.guild.get_channel(channel_id)
                    if channel:
                        channel_names.append(f"<#{channel_id}> ({channel.name})")
                    else:
                        channel_names.append(f"<#{channel_id}> (deleted)")
            
            # Limit display to prevent embed overflow
            if len(channel_names) > 10:
                channels_text = "\n".join(channel_names[:10]) + f"\n*+{len(channel_names) - 10} more*"
            else:
                channels_text = "\n".join(channel_names)
            
            embed.add_field(name=f"{len(exempt_channels_data)} Exempt Channels", value=channels_text, inline=False)
        else:
            embed.add_field(name="0 Exempt Channels", value="None", inline=False)
        
        await ctx.reply(embed=embed)

    @invite_whitelist.command(name="enable")
    async def invite_enable(self, ctx: commands.Context):
        """Enable the AutoMod invite rule."""
        rule = await self.find_invite_rule(ctx.guild)
        
        if not rule:
            await ctx.reply(error(f"{ctx.author.mention} AutoMod rule '{DEFAULT_RULE_NAME}' not found. Use `{ctx.prefix}invite add <code>` to create it."))
            return
        
        if rule.enabled:
            await ctx.reply(info(f"{ctx.author.mention} Rule is already enabled."))
            return
        
        try:
            await rule.edit(enabled=True, reason="Enabled by InWhitelist cog")
            await ctx.reply(success(f"{ctx.author.mention} Enabled AutoMod rule '{DEFAULT_RULE_NAME}'."))
            await checkmark(ctx)
        except discord.Forbidden:
            await ctx.reply(error(f"{ctx.author.mention} Bot lacks permission to edit AutoMod rules."))
        except discord.HTTPException as e:
            await ctx.reply(error(f"{ctx.author.mention} Failed to enable rule: {e}"))

    @invite_whitelist.command(name="disable")
    async def invite_disable(self, ctx: commands.Context):
        """Disable the AutoMod invite rule."""
        rule = await self.find_invite_rule(ctx.guild)
        
        if not rule:
            await ctx.reply(error(f"{ctx.author.mention} AutoMod rule '{DEFAULT_RULE_NAME}' not found."))
            return
        
        if not rule.enabled:
            await ctx.reply(info(f"{ctx.author.mention} Rule is already disabled."))
            return
        
        try:
            await rule.edit(enabled=False, reason="Disabled by InWhitelist cog")
            await ctx.reply(success(f"{ctx.author.mention} Disabled AutoMod rule '{DEFAULT_RULE_NAME}'."))
            await checkmark(ctx)
        except discord.Forbidden:
            await ctx.reply(error(f"{ctx.author.mention} Bot lacks permission to edit AutoMod rules."))
        except discord.HTTPException as e:
            await ctx.reply(error(f"{ctx.author.mention} Failed to disable rule: {e}"))

    @invite_whitelist.command(name="clear")
    async def invite_clear(self, ctx: commands.Context):
        """Clear all whitelisted invites."""
        rule = await self.find_invite_rule(ctx.guild)
        
        if not rule:
            await ctx.reply(error(f"{ctx.author.mention} AutoMod rule '{DEFAULT_RULE_NAME}' not found."))
            return
        
        allowlist = rule.trigger.allow_list or []
        if not allowlist:
            await ctx.reply(info(f"{ctx.author.mention} No invites to clear."))
            return
        
        # Confirmation
        await ctx.reply(
            f"⚠️ **WARNING**: {ctx.author.mention} This will remove {len(allowlist)} whitelisted invite(s). "
            f"Type `CONFIRM CLEAR` to proceed or anything else to cancel."
        )
        
        def check(message):
            return (message.author == ctx.author and 
                   message.channel == ctx.channel)
        
        try:
            response = await self.bot.wait_for('message', check=check, timeout=30.0)
            if response.content != 'CONFIRM CLEAR':
                await ctx.reply(f"{ctx.author.mention} Clear cancelled.")
                return
        except Exception:
            await ctx.reply(f"{ctx.author.mention} Clear cancelled due to timeout.")
            return
        
        try:
            await self.update_rule_allowlist(rule, [])
            await ctx.reply(success(f"{ctx.author.mention} Cleared {len(allowlist)} invite(s) from whitelist."))
            await checkmark(ctx)
        except ValueError as e:
            await ctx.reply(error(f"{ctx.author.mention} {str(e)}"))

    @invite_whitelist.command(name="prune", aliases=["cleanup", "clean", "purge"])
    async def invite_prune(self, ctx: commands.Context):
        """Remove invalid/expired invites from the whitelist."""
        # Find rule
        rule = await self.find_invite_rule(ctx.guild)
        
        if not rule:
            await ctx.reply(error(f"{ctx.author.mention} AutoMod rule '{DEFAULT_RULE_NAME}' not found."))
            return
        
        # Get allow list
        allowlist = rule.trigger.allow_list or []
        
        if not allowlist:
            await ctx.reply(info(f"{ctx.author.mention} No invites to prune."))
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
        
        # Check each invite
        invalid_invites = []
        valid_invites = []
        
        await ctx.reply(info(f"{ctx.author.mention} Checking {len(invite_codes)} invite(s) for validity..."))
        
        for code in invite_codes:
            try:
                # Try to resolve the invite
                invite_info = await self.resolve_invite(code)
                if invite_info:
                    valid_invites.append(code)
                else:
                    invalid_invites.append(code)
            except Exception:
                # Any error means the invite is invalid
                invalid_invites.append(code)
        
        if not invalid_invites:
            await ctx.reply(success(f"{ctx.author.mention} All {len(valid_invites)} invites are valid. Nothing to prune."))
            await checkmark(ctx)
            return
        
        # Build embed showing what will be removed
        embed = discord.Embed(
            title=f"Pruning {len(invalid_invites)} Invalid Invites",
            description=f"Found {len(invalid_invites)} invalid invite(s) out of {len(invite_codes)} total.",
            color=discord.Color.orange()
        )
        
        # List invalid invites
        invalid_list = []
        for code in invalid_invites:
            invalid_list.append(f"`{code}` - *Invalid/Expired*")
        
        # Limit display to prevent embed overflow
        if len(invalid_list) > 10:
            invalid_text = "\n".join(invalid_list[:10]) + f"\n*+{len(invalid_list) - 10} more*"
        else:
            invalid_text = "\n".join(invalid_list)
        
        embed.add_field(name="Invalid Invites to Remove", value=invalid_text, inline=False)
        
        # Show valid invites count
        if valid_invites:
            embed.add_field(name="Valid Invites", value=f"{len(valid_invites)} invites will be kept", inline=False)
        
        embed.set_footer(text="Reply with 'CONFIRM PRUNE' to proceed or anything else to cancel")
        
        await ctx.reply(embed=embed)
        
        # Wait for confirmation
        def check(message):
            return (message.author == ctx.author and 
                   message.channel == ctx.channel)
        
        try:
            response = await self.bot.wait_for('message', check=check, timeout=30.0)
            if response.content != 'CONFIRM PRUNE':
                await ctx.reply(f"{ctx.author.mention} Prune cancelled.")
                return
        except Exception:
            await ctx.reply(f"{ctx.author.mention} Prune cancelled due to timeout.")
            return
        
        # Remove invalid invites from allowlist
        new_allowlist = []
        for item in allowlist:
            # Check if this item contains any of the invalid codes
            is_invalid = False
            for invalid_code in invalid_invites:
                if invalid_code in item:
                    is_invalid = True
                    break
            if not is_invalid:
                new_allowlist.append(item)
        
        try:
            await self.update_rule_allowlist(rule, new_allowlist)
            
            # Clear cached info for invalid invites
            guild_config = self.config.guild(ctx.guild)
            async with guild_config.invite_cache() as cache:
                for code in invalid_invites:
                    if code in cache:
                        del cache[code]
            
            await ctx.reply(success(f"{ctx.author.mention} Pruned {len(invalid_invites)} invalid invite(s). {len(valid_invites)} valid invite(s) remain."))
            await checkmark(ctx)
        except ValueError as e:
            await ctx.reply(error(f"{ctx.author.mention} {str(e)}"))
