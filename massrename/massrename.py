"""MassRename cog for Red-DiscordBot"""

import csv
import io
import shlex
from typing import List, Optional, Union
import logging
import random

import asyncio
import aiohttp
import discord
from redbot.core import Config, checks, commands
from redbot.core.bot import Red
from redbot.core.utils.predicates import MessagePredicate

log = logging.getLogger("red.blu.massrename")

class MassRename(commands.Cog):
    """Mass renames guild members to random names from a list."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=2349872395, force_registration=True)
        
        default_guild = {
            "names": [],  # List of strings
            "backups": {}  # Dict[str, Optional[str]] mapping user ID to original nickname (or None)
        }
        self.config.register_guild(**default_guild)

    async def fetch_names_from_url(self, url: str) -> List[str]:
        """Fetch and parse names from a CSV or TXT URL."""
        names = []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        return []
                    content = await response.text()
            
            # Determine if CSV or TXT based on URL or content
            is_csv = url.lower().endswith(".csv") or "," in content.splitlines()[0]
            
            if is_csv:
                f = io.StringIO(content)
                reader = csv.reader(f)
                for row in reader:
                    if not row:
                        continue
                    name = row[0].strip()
                    if name and name.lower() not in ("name", "username"):
                        names.append(name)
            else:
                for line in content.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or line.lower() in ("name", "username"):
                        continue
                    if "," in line:
                        parts = [p.strip() for p in line.split(",")]
                        name = parts[0]
                    else:
                        name = line
                    if name and name.lower() not in ("name", "username"):
                        names.append(name)
        except Exception as e:
            log.error(f"Error fetching names from URL: {e}")
        return names

    @commands.group(invoke_without_command=True)
    @checks.admin_or_permissions(manage_nicknames=True)
    async def massrename(self, ctx: commands.Context, *, args: str = None):
        """Configure the MassRename cog or add names.
        
        Run without arguments to show current names count.
        Provide a name to set the active names list to that single name.
        Provide a CSV/TXT URL to load names from a file.
        """
        if args is None:
            current_names = await self.config.guild(ctx.guild).names()
            await ctx.send(f"MassRename has {len(current_names)} names configured.")
            return

        try:
            parsed = shlex.split(args)
        except Exception:
            parsed = args.split()

        if not parsed:
            return

        first_arg = parsed[0]
        if first_arg.startswith(("http://", "https://")):
            await ctx.typing()
            new_names = await self.fetch_names_from_url(first_arg)
            if new_names:
                await self.config.guild(ctx.guild).names.set(new_names)
                await ctx.send(f"Successfully loaded and set {len(new_names)} names.")
                await ctx.message.add_reaction("✅")
            else:
                await ctx.send("Failed to load names from the URL. Ensure the format is correct.")
                await ctx.message.add_reaction("❌")
        else:
            name = args.strip().strip('"')
            await self.config.guild(ctx.guild).names.set([name])
            await ctx.send(f"Set name list to '{name}' successfully.")
            await ctx.message.add_reaction("✅")

    @massrename.command(name="start")
    @checks.admin_or_permissions(manage_nicknames=True)
    async def massrename_start(self, ctx: commands.Context):
        """Start mass renaming all server members."""
        names = await self.config.guild(ctx.guild).names()
        if not names:
            await ctx.send("Please configure some names first using `!massrename {url}` or `!massrename {name}`.")
            await ctx.message.add_reaction("❌")
            return

        # Check bot permissions
        me = ctx.guild.me
        if not me.guild_permissions.manage_nicknames:
            await ctx.send("I do not have the 'Manage Nicknames' permission in this server.")
            await ctx.message.add_reaction("❌")
            return

        await ctx.send("Starting mass rename process... This may take a while depending on server size.")
        
        # Gather all renameable members (including the guild owner and this bot itself)
        members = ctx.guild.members
        renameable_members = []
        for member in members:
            if member.top_role < me.top_role or member.id == ctx.guild.owner_id or member.id == me.id:
                renameable_members.append(member)

        if not renameable_members:
            await ctx.send("No renameable members found (they are either bots, the guild owner, or have higher/equal roles than me).")
            return

        # Show preview and ask for confirmation
        members_with_nick = [m for m in renameable_members if m.nick]
        preview_lines = []
        for member in members_with_nick[:15]:
            preview_lines.append(f"- {member.name} (original nick: {member.nick})")
        if len(members_with_nick) > 15:
            preview_lines.append(f"... and {len(members_with_nick) - 15} more members with custom nicknames.")
        
        preview_text = "\n".join(preview_lines) if preview_lines else "None of the target members have custom nicknames."
        
        confirmation_msg = (
            f"Found **{len(renameable_members)}** members to rename. Here is a preview of the members and their current nicknames:\n"
            f"{preview_text}\n\n"
            "Are you sure you want to proceed with the mass rename? (yes/no)"
        )
        await ctx.send(confirmation_msg)

        try:
            pred = MessagePredicate.yes_or_no(ctx)
            await self.bot.wait_for("message", check=pred, timeout=30.0)
        except asyncio.TimeoutError:
            await ctx.send("Mass rename cancelled (timeout).")
            await ctx.message.add_reaction("❌")
            return

        if not pred.result:
            await ctx.send("Mass rename cancelled.")
            await ctx.message.add_reaction("❌")
            return

        await ctx.send("Starting mass rename process... This may take a while depending on server size.")
        
        # Backup nicknames before modifying them
        async with self.config.guild(ctx.guild).backups() as backups:
            for member in renameable_members:
                str_id = str(member.id)
                if str_id not in backups:
                    backups[str_id] = member.nick

        success_count = 0
        fail_count = 0

        # Shuffle and draw names
        shuffled_names = list(names)
        random.shuffle(shuffled_names)

        for member in renameable_members:
            if not shuffled_names:
                shuffled_names = list(names)
                random.shuffle(shuffled_names)
            
            name_to_assign = shuffled_names.pop()
            try:
                await member.edit(nick=name_to_assign)
                success_count += 1
            except discord.Forbidden:
                fail_count += 1
            except discord.HTTPException as e:
                log.error(f"HTTP error renaming member {member.id}: {e}")
                fail_count += 1

        await ctx.send(f"Mass renaming completed. Renamed {success_count} members. Failed for {fail_count} members.")
        await ctx.message.add_reaction("✅")

    @massrename.command(name="end")
    @checks.admin_or_permissions(manage_nicknames=True)
    async def massrename_end(self, ctx: commands.Context):
        """Restore all members to their backed-up nicknames and clear backups."""
        backups = await self.config.guild(ctx.guild).backups()
        if not backups:
            await ctx.send("No nicknames backup found for this server.")
            await ctx.message.add_reaction("❌")
            return

        # Check bot permissions
        me = ctx.guild.me
        if not me.guild_permissions.manage_nicknames:
            await ctx.send("I do not have the 'Manage Nicknames' permission in this server.")
            await ctx.message.add_reaction("❌")
            return

        await ctx.send("Restoring original nicknames... This may take a while depending on server size.")

        success_count = 0
        fail_count = 0

        # Create a copy to iterate while we update config
        backups_copy = dict(backups)

        for str_id, old_nick in backups_copy.items():
            member_id = int(str_id)
            member = ctx.guild.get_member(member_id)
            if not member:
                # Member left the guild, just remove from backup
                async with self.config.guild(ctx.guild).backups() as current_backups:
                    current_backups.pop(str_id, None)
                continue

            if member.top_role >= me.top_role:
                fail_count += 1
                continue

            try:
                await member.edit(nick=old_nick)
                success_count += 1
                async with self.config.guild(ctx.guild).backups() as current_backups:
                    current_backups.pop(str_id, None)
            except discord.Forbidden:
                fail_count += 1
            except discord.HTTPException as e:
                log.error(f"HTTP error restoring nickname for {member.id}: {e}")
                fail_count += 1

        # Clear remaining backups if any
        await self.config.guild(ctx.guild).backups.set({})
        
        await ctx.send(f"Restoration completed. Restored {success_count} members. Failed/Skipped for {fail_count} members.")
        await ctx.message.add_reaction("✅")
