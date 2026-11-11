"""Bluscream cog for Red-DiscordBot: small utility commands.

Scam softbans moved to the standalone, intent-free scambot (Bluscream/bluscream-scambot).
"""

from __future__ import annotations

import io
import logging
from typing import TYPE_CHECKING, Any

import discord
from redbot.core import Config, commands
from redbot.core.utils.chat_formatting import box, error, success

if TYPE_CHECKING:
    from discord.ext.commands import Command as DpyCommand
    from redbot.core.bot import Red

log = logging.getLogger("red.blu.bluscream")

INLINE_DUMP_MAX = 1900  # leaves room for the note and code fence under Discord's 2000


class Bluscream(commands.Cog):
    """Small utility commands (prefix, mention and slash)."""

    __author__ = "Bluscream"
    __version__ = "3.0.0"

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        # Kept so settings written by earlier versions stay readable and removable.
        self.config = Config.get_conf(
            self, identifier=928374561, force_registration=True
        )
        self.config.register_global(schema_version=1)

    async def red_delete_data_for_user(self, *, requester: str, user_id: int) -> None:
        """No per-user data is stored."""
        del requester, user_id

    # Red re-exports discord.py's hybrid_group with a Context bound mypy cannot unify with Red's
    # own Context when the decorator gets the bare method (the `role` group gets the output of
    # the untyped check decorators instead, so it is not affected).
    @commands.hybrid_group(name="bluscream", aliases=["blu"], fallback="help")  # type: ignore[arg-type]
    async def bluscream(self, ctx: commands.Context) -> None:
        """Bluscream utility commands."""
        await ctx.send_help(ctx.command)

    @bluscream.command(name="dumpcmds")
    @commands.is_owner()
    async def dumpcmds(self, ctx: commands.Context) -> None:
        """Dump all commands as CSV: cog;command;aliases;arguments."""
        rows = sorted(
            (
                (
                    cmd.cog_name or "No Cog",
                    cmd.qualified_name,
                    ",".join(cmd.aliases),
                    _signature(cmd),
                )
                for cmd in self.bot.walk_commands()
            ),
            key=lambda row: (row[0], row[1]),
        )
        lines = ["cog;command;comma_separated_aliases;arguments"]
        lines += [";".join(field.replace(";", "\\;") for field in row) for row in rows]
        content = "\n".join(lines)
        note = success(f"Generated command dump with {len(rows)} commands.")
        if len(content) > INLINE_DUMP_MAX:
            await ctx.send(
                note,
                file=discord.File(io.BytesIO(content.encode()), "commands_dump.csv"),
            )
        else:
            await ctx.send(f"{note}\n{box(content, lang='csv')}")

    @commands.hybrid_group(name="role", fallback="help")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_roles=True)
    async def role(self, ctx: commands.GuildContext) -> None:
        """Role management commands."""
        await ctx.send_help(ctx.command)

    @role.command(name="add")
    @commands.bot_has_permissions(manage_roles=True)
    async def role_add(
        self, ctx: commands.GuildContext, name: str, color: str = ""
    ) -> None:
        """Create a role without permissions at the bottom of the list.

        `color` is a hex code like #ff00aa; a random colour is used when it is empty.
        """
        try:
            colour = discord.Color.from_str(color) if color else discord.Color.random()
        except ValueError:
            await ctx.send(
                error(f"`{color}` is not a colour; use a hex code like #ff00aa.")
            )
            return
        new_role = await ctx.guild.create_role(
            name=name,
            color=colour,
            permissions=discord.Permissions.none(),
            reason=f"Created by {ctx.author} ({ctx.author.id}) via bluscream cog",
        )
        await new_role.edit(position=1)
        await ctx.send(success(f"Role **{name}** created at the bottom of the list."))

    @commands.Cog.listener()
    async def on_command(self, ctx: commands.Context) -> None:
        """Log command use at debug level (large servers make INFO too noisy)."""
        log.debug(
            "Command %s by %s in %s/%s",
            ctx.command,
            ctx.author.id,
            ctx.guild.id if ctx.guild else "DM",
            ctx.channel.id,
        )


def _signature(command: DpyCommand[Any, ..., Any]) -> str:
    """Render a command's parameters as `<required>` / `[optional]`."""
    parts = []
    for name, param in command.clean_params.items():
        dots = "..." if param.kind is param.VAR_POSITIONAL else ""
        parts.append(
            f"<{name}{dots}>" if param.default is param.empty else f"[{name}{dots}]"
        )
    return " ".join(parts)
