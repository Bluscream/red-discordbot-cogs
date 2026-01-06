"""Shared library for Bluscream's cogs."""

import discord
from redbot.core import commands
from redbot.core.utils.chat_formatting import error


async def checkmark(ctx: commands.Context) -> None:
    """Add a checkmark reaction to a message."""
    try:
        await ctx.message.add_reaction("✅")
    except discord.HTTPException:
        pass


async def delete(ctx: commands.Context, delay: int = 0) -> None:
    """Delete a message after a delay."""
    try:
        await ctx.message.delete(delay=delay)
    except discord.HTTPException:
        pass
