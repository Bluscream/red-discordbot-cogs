"""Bluscream cog for Red-DiscordBot - Utility commands"""

from typing import ClassVar, Dict, List, Optional, Union
from logging import getLogger
import io

import discord
from redbot.core import Config, checks, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import error, info, success, warning, box

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

    # Error handling
    async def cog_command_error(self, ctx: commands.Context, error: Exception):
        """Handle command errors."""
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(error("You don't have permission to use this command."))
        elif isinstance(error, commands.BotMissingPermissions):
            await ctx.send(error("I don't have the required permissions to perform this action."))
        elif isinstance(error, commands.CheckFailure):
            await ctx.send(error("Command check failed."))
        else:
            log.error(f"Unexpected error in {ctx.command}: {error}")
            await ctx.send(error("An unexpected error occurred. Please try again later."))
