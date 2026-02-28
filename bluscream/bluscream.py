"""Bluscream cog for Red-DiscordBot - Utility commands"""

from typing import ClassVar, Dict, List, Optional, Union
from logging import getLogger
import io
from datetime import datetime

import discord
from redbot.core import Config, checks, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import error, info, success, warning, box
import asyncio

log = getLogger("red.blu.bluscream")


class Bluscream(commands.Cog):
    """
    Utility commands for bot management and debugging.
    """

    __author__ = "Bluscream"
    __version__ = "1.0.0"

    default_global_settings: ClassVar[dict[str, Union[int, dict, List[int]]]] = {
        "schema_version": 1
    }

    def __init__(self, bot: Red) -> None:
        """Set up the cog."""
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=928374561, force_registration=True
        )
        self.config.register_global(**self.default_global_settings)

    async def cog_load(self) -> None:
        """Called when the cog is loaded."""
        log.info("Bluscream cog loaded successfully")

    @commands.Cog.listener()
    async def on_command(self, ctx: commands.Context):
        """Log all command executions."""
        guild_name = ctx.guild.name if ctx.guild else "DM"
        guild_id = ctx.guild.id if ctx.guild else "DM"
        channel_name = ctx.channel.name if hasattr(ctx.channel, 'name') else f"DM-{ctx.channel.id}"
        
        log.info(
            f"Command executed: {ctx.command} "
            f"by {ctx.author} (ID: {ctx.author.id}) "
            f"in #{channel_name} (ID: {ctx.channel.id}) "
            f"in {guild_name} (ID: {guild_id})"
        )

    def _build_message_link(self, guild_id: int, channel_id: int, message_id: int, domain: str = "") -> str:
        """Build a Discord message link from guild, channel, and message IDs."""
        domain = domain or "discord.com"
        return f"https://{domain}/channels/{guild_id}/{channel_id}/{message_id}"
    
    def _build_message_link_from_msg(self, message: discord.Message, domain: str = "") -> str:
        """Build a Discord message link from a message object."""
        return self._build_message_link(message.guild.id, message.channel.id, message.id, domain)

    def _format_command_signature(self, command: commands.Command) -> str:
        """Format a command signature with its parameters."""
        if not command.parent:  # Root command
            signature = command.name
        else:  # Subcommand
            signature = f"{command.parent.name} {command.name}"
        
        # Add parameters
        if command.clean_params:
            params = []
            for param_name, param in command.clean_params.items():
                if param.default == param.empty:
                    if param.kind == param.VAR_POSITIONAL:
                        params.append(f"<{param_name}...>")
                    else:
                        params.append(f"<{param_name}>")
                else:
                    if param.kind == param.VAR_POSITIONAL:
                        params.append(f"[{param_name}...]")
                    else:
                        params.append(f"[{param_name}]")
            signature += " " + " ".join(params)
        
        return signature

    def _get_command_arguments(self, command: commands.Command) -> str:
        """Get command arguments as a formatted string."""
        if not command.clean_params:
            return ""
        
        args = []
        for param_name, param in command.clean_params.items():
            if param.default == param.empty:
                if param.kind == param.VAR_POSITIONAL:
                    args.append(f"<{param_name}...>")
                else:
                    args.append(f"<{param_name}>")
            else:
                if param.kind == param.VAR_POSITIONAL:
                    args.append(f"[{param_name}...]")
                else:
                    args.append(f"[{param_name}]")
        
        return " ".join(args)

    def _get_cog_name(self, command: commands.Command) -> str:
        """Get the cog name for a command."""
        return command.cog_name or "No Cog"

    async def _react_or_send(self, ctx: commands.Context, emoji: str, message: str):
        """Try to react with an emoji, or send a message if reaction permissions are missing."""
        if ctx.channel.permissions_for(ctx.me).add_reactions:
            try:
                await ctx.message.add_reaction(emoji)
                return
            except discord.HTTPException:
                pass
        await ctx.send(message)

    @commands.group(name="bluscream", aliases=["blu"], invoke_without_command=True)
    async def bluscream(self, ctx: commands.Context):
        """Bluscream utility commands."""
        await ctx.send_help(ctx.command)

    @bluscream.command(name="dumpcmds")
    @commands.is_owner()
    async def dumpcmds(self, ctx: commands.Context):
        """
        Dump all commands to CSV format.
        
        Format: cog;command;comma_separated_aliases;arguments
        """
        await ctx.send(info("Generating command dump... This may take a moment."))

        # Collect all commands
        all_commands = []
        
        def walk_commands(commands_list: List[commands.Command], parent: Optional[str] = None, cog_name: Optional[str] = None):
            for command in commands_list:
                if isinstance(command, commands.Group):
                    # Add the group command itself
                    full_name = f"{parent} {command.name}".strip() if parent else command.name
                    aliases = ",".join(command.aliases) if command.aliases else ""
                    args = self._get_command_arguments(command)
                    actual_cog_name = cog_name or self._get_cog_name(command)
                    all_commands.append((actual_cog_name, full_name, aliases, args))
                    
                    # Recursively walk subcommands
                    walk_commands(list(command.commands), full_name, actual_cog_name)
                else:
                    # Regular command
                    full_name = f"{parent} {command.name}".strip() if parent else command.name
                    aliases = ",".join(command.aliases) if command.aliases else ""
                    args = self._get_command_arguments(command)
                    actual_cog_name = cog_name or self._get_cog_name(command)
                    all_commands.append((actual_cog_name, full_name, aliases, args))

        # Walk all cogs and commands
        for cog_name, cog in self.bot.cogs.items():
            if hasattr(cog, 'walk_commands'):
                walk_commands(list(cog.walk_commands()), cog_name=cog_name)
        
        # Also walk bot's own commands (not in cogs)
        walk_commands(list(self.bot.walk_commands()), cog_name="Bot Commands")

        # Remove duplicates and sort
        unique_commands = list(set(all_commands))
        unique_commands.sort(key=lambda x: (x[0], x[1]))  # Sort by cog name, then command name

        # Generate CSV content
        csv_lines = ["cog;command;comma_separated_aliases;arguments"]
        for cog_name, cmd_name, aliases, args in unique_commands:
            # Escape semicolons in the data
            cog_name_escaped = cog_name.replace(";", "\\;")
            cmd_name_escaped = cmd_name.replace(";", "\\;")
            aliases_escaped = aliases.replace(";", "\\;")
            args_escaped = args.replace(";", "\\;")
            csv_lines.append(f"{cog_name_escaped};{cmd_name_escaped};{aliases_escaped};{args_escaped}")

        csv_content = "\n".join(csv_lines)

        # Send as file if too long, otherwise as code block
        if len(csv_content) > 1900:  # Discord message limit
            # Send as file
            file = discord.File(
                io.StringIO(csv_content),
                filename="commands_dump.csv"
            )
            await ctx.send(file=file, content=success(f"Generated command dump with {len(unique_commands)} commands."))
        else:
            # Send as code block
            await ctx.send(
                box(csv_content, lang="csv"),
                content=success(f"Generated command dump with {len(unique_commands)} commands:")
            )

    @commands.command(name="scam")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True, read_message_history=True)
    async def scam(self, ctx: commands.Context, *, reason: str = None):
        """
        Ban the user from the replied message, purge last 7 days, then unban after 1 second.
        
        Args:
            reason: Optional reason for the ban. If not provided, uses "Scam: <message link>"
        """
        if not ctx.message.reference:
            await ctx.send(error("You must reply to a message to use this command."))
            return
        
        try:
            # Get the referenced message
            referenced_message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            target_user = referenced_message.author
            
            async with ctx.typing():
                # Collect user information before banning
                user_info = {
                    "username": str(target_user),
                    "userid": target_user.id,
                    "created_at": int(target_user.created_at.timestamp()),  # Unix timestamp for Discord format
                    "joined_at": None,
                    "message_count": 0
                }
                
                # Get join date if user is still in server
                try:
                    member = ctx.guild.get_member(target_user.id)
                    if member and member.joined_at:
                        user_info["joined_at"] = int(member.joined_at.timestamp())  # Unix timestamp for Discord format
                except:
                    pass
                
                # Count total messages from user using search API
                try:
                    # Use the search API endpoint directly
                    search_url = f"/guilds/{ctx.guild.id}/messages/search"
                    search_params = {
                        "author_id": target_user.id,
                        "limit": 100  # Get count from search results
                    }
                    
                    search_result = await ctx.bot.http.request(
                        discord.http.Route('GET', search_url, guild_id=ctx.guild.id),
                        params=search_params
                    )
                    
                    if search_result and "total_results" in search_result:
                        user_info["message_count"] = search_result["total_results"]
                    else:
                        user_info["message_count"] = "Search unavailable"
                except Exception as e:
                    # Fallback to manual iteration if search fails
                    try:
                        message_count = 0
                        async for message in ctx.channel.history(limit=1000):
                            if message.author.id == target_user.id:
                                message_count += 1
                        user_info["message_count"] = f"{message_count} (manual count)"
                    except:
                        user_info["message_count"] = "Unable to count"
                
                # Generate message link for default reason
                if not reason:
                    reason = f"Scam: {self._build_message_link_from_msg(referenced_message)}"
                
                # Ban the user and purge last 7 days
                await ctx.guild.ban(target_user, reason=reason, delete_message_seconds=60*60*24*7)
                
                # Send summary to specified channel if in specific server
                summary_message = None
                if ctx.guild.id == 747967102895390741:
                    try:
                        summary_channel = ctx.guild.get_channel(896433099100016750)
                        if summary_channel:
                            summary_embed = discord.Embed(
                                title="",
                                color=discord.Color.red(),
                                timestamp=discord.utils.utcnow()
                            )
                            uid = user_info["userid"]
                            summary_embed.add_field(name="User", value=target_user.mention, inline=True)
                            summary_embed.add_field(name="User ID", value=f"`{uid}`", inline=True)
                            summary_embed.add_field(name="Account Created", value=f"<t:{user_info['created_at']}:R>" if user_info["created_at"] else "Not available", inline=False)
                            summary_embed.add_field(name="Join Date", value=f"<t:{user_info['joined_at']}:R>" if user_info["joined_at"] else "Not available", inline=False)
                            summary_embed.add_field(name="Message Count", value=str(user_info["message_count"]), inline=False)
                            summary_embed.add_field(name="Reason", value=reason, inline=False)
                            summary_embed.add_field(name="Moderator", value=ctx.author.mention, inline=False)
                            summary_embed.set_footer(text=f"{datetime.now()}")
                            
                            summary_message = await summary_channel.send(embed=summary_embed)
                    except Exception as e:
                        log.warning(f"Failed to send scam summary to channel: {e}")
                
                # Wait 1 second then unban
                await asyncio.sleep(1)
                
                # Use summary message link as unban reason if available, otherwise default reason
                unban_reason = "Temporary scam ban"
                if summary_message:
                    unban_reason = self._build_message_link_from_msg(summary_message)
                
                await ctx.guild.unban(target_user, reason=unban_reason)
            
            # Add check mark reaction to command message
            await self._react_or_send(ctx, "✅", success("Scam ban completed successfully."))
            
        except discord.NotFound as e:
            log.error(e)
            await self._react_or_send(ctx, "❓", error("The referenced message could not be found."))
        except discord.Forbidden as e:
            log.error(e)
            await self._react_or_send(ctx, "🚫", error("I don't have permission to perform this action."))
        except Exception as e:
            log.error(e)
            await self._react_or_send(ctx, "❌", error(f"An error occurred: {str(e)}"))

    @commands.group(name="role")
    @commands.guild_only()
    @commands.has_permissions(manage_roles=True)
    async def role(self, ctx: commands.Context):
        """Role management commands."""
        pass

    @role.command(name="add")
    @commands.bot_has_permissions(manage_roles=True)
    async def role_add(self, ctx: commands.Context, name: str, color: Optional[discord.Color] = None):
        """
        Add a role with no permissions on the bottom of the role list.
        
        Args:
            name: The name of the new role.
            color: The color of the new role (hex code or name). If omitted, uses a random color.
        """
        if color is None:
            color = discord.Color.random()
        
        async with ctx.typing():
            try:
                # Create the role with no permissions
                new_role = await ctx.guild.create_role(
                    name=name,
                    color=color,
                    permissions=discord.Permissions.none(),
                    reason=f"Created by {ctx.author} ({ctx.author.id}) via bluscream cog"
                )
                
                # Move to bottom (position 1 is just above @everyone)
                await new_role.edit(position=1)
                
                await self._react_or_send(ctx, "✅", success(f"Role **{name}** created and moved to the bottom of the list."))
            except discord.Forbidden:
                await self._react_or_send(ctx, "🚫", error("I do not have permission to manage roles."))
            except discord.HTTPException as e:
                await self._react_or_send(ctx, "❌", error(f"Failed to create role: {e}"))

    # Error handling
    async def cog_command_error(self, ctx: commands.Context, error: Exception):
        """Handle command errors."""
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(error("You don't have permission to use this command."))
        elif isinstance(error, commands.BotMissingPermissions):
            await ctx.send(error("I don't have the required permissions to perform this action."))
        elif isinstance(error, commands.CheckFailure):
            await ctx.send(error("Command check failed."))
        elif isinstance(error, commands.CommandInvokeError):
            # Handle the wrapped exception
            original_error = error.original
            if isinstance(original_error, commands.BotMissingPermissions):
                await ctx.send(error("I don't have the required permissions to perform this action."))
            else:
                log.error(f"Unexpected error in {ctx.command}: {original_error}")
                await ctx.send(error("An unexpected error occurred. Please try again later."))
        else:
            log.error(f"Unexpected error in {ctx.command}: {error}")
            await ctx.send(error("An unexpected error occurred. Please try again later."))
