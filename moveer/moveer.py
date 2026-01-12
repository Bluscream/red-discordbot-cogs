"""Moveer cog for Red-DiscordBot - Voice channel management commands"""

from typing import ClassVar, Dict, List, Optional, Union
from logging import getLogger
import asyncio

import discord
from redbot.core import Config, checks, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import error, info, success, warning, box

log = getLogger("red.blu.moveer")


class Moveer(commands.Cog):
    """
    Voice channel management commands inspired by Moveer bot.
    
    This cog provides comprehensive voice channel management functionality including:
    - Moving users between voice channels
    - Disconnecting users from voice
    - Role-based voice movements
    - Category-based operations
    - User counting in channels
    """

    __author__ = "Bluscream"
    __version__ = "1.0.0"

    default_global_settings: ClassVar[dict[str, Union[int, dict, List[int]]]] = {
        "schema_version": 1,
        "move_history": [],
        "statistics": {
            "total_moves": 0,
            "total_disconnects": 0,
            "commands_used": {}
        }
    }

    default_guild_settings: ClassVar[dict[str, dict]] = {
        "settings": {
            "require_permission": True,
            "log_moves": False,
            "max_users_per_move": 50
        }
    }

    def __init__(self, bot: Red) -> None:
        """Set up the cog."""
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=284739201, force_registration=True
        )
        self.config.register_global(**self.default_global_settings)
        self.config.register_guild(**self.default_guild_settings)

    async def cog_load(self) -> None:
        """Called when the cog is loaded."""
        log.info("Moveer cog loaded successfully")

    def _get_user_voice_channel(self, member: discord.Member) -> Optional[discord.VoiceChannel]:
        """Get the voice channel a user is currently in."""
        voice_state = member.guild.voice_states.get(member.id)
        return voice_state.channel if voice_state else None

    def _is_connected_to_voice(self, member: discord.Member) -> bool:
        """Check if a user is connected to voice."""
        return self._get_user_voice_channel(member) is not None

    async def _can_move_user(self, ctx: commands.Context, target: discord.Member, target_channel: discord.VoiceChannel) -> bool:
        """Check if the bot has permission to move a user to the target channel."""
        # Check if target is in voice
        if not self._is_connected_to_voice(target):
            return False
        
        # Check bot permissions
        bot_member = ctx.guild.me
        if not bot_member.guild_permissions.move_members:
            return False
        
        # Check channel permissions
        if not target_channel.permissions_for(bot_member).connect:
            return False
        
        # Check user hierarchy
        if target.top_role >= bot_member.top_role and target.guild.owner != target:
            return False
        
        return True

    async def _move_users_batch(self, ctx: commands.Context, users: List[discord.Member], 
                               target_channel: discord.VoiceChannel, command_name: str) -> Dict[str, int]:
        """Move a batch of users and return statistics."""
        moved = 0
        failed = 0
        
        for user in users:
            if await self._can_move_user(ctx, user, target_channel):
                try:
                    await user.move_to(target_channel)
                    moved += 1
                    await asyncio.sleep(0.1)  # Rate limiting
                except discord.HTTPException as e:
                    log.warning(f"Failed to move {user}: {e}")
                    failed += 1
            else:
                failed += 1
        
        # Update statistics
        async with self.config.statistics() as stats:
            stats["total_moves"] += moved
            if command_name not in stats["commands_used"]:
                stats["commands_used"][command_name] = 0
            stats["commands_used"][command_name] += 1
        
        return {"moved": moved, "failed": failed}

    @commands.group(name="moveer", invoke_without_command=True)
    async def moveer(self, ctx: commands.Context):
        """Voice channel management commands."""
        await ctx.send_help(ctx.command)

    @moveer.command(name="move")
    @commands.has_permissions(move_members=True)
    @commands.bot_has_permissions(move_members=True)
    async def move(self, ctx: commands.Context, user1: discord.Member, 
                   user2: Optional[discord.Member] = None, 
                   user3: Optional[discord.Member] = None,
                   user4: Optional[discord.Member] = None,
                   user5: Optional[discord.Member] = None,
                   user6: Optional[discord.Member] = None):
        """
        Move users to your voice channel.
        
        You must be in a voice channel to use this command.
        """
        author_voice = self._get_user_voice_channel(ctx.author)
        if not author_voice:
            await ctx.send(error("You need to be in a voice channel to use this command."))
            return

        users = [u for u in [user1, user2, user3, user4, user5, user6] if u is not None]
        connected_users = [u for u in users if self._is_connected_to_voice(u)]
        
        if not connected_users:
            await ctx.send(warning("None of the specified users are in voice channels."))
            return

        stats = await self._move_users_batch(ctx, connected_users, author_voice, "move")
        
        message = f"Moved {stats['moved']} user{'s' if stats['moved'] != 1 else ''} to {author_voice.mention}"
        if stats['failed'] > 0:
            message += f"\n{warning('Failed to move ' + str(stats['failed']) + ' user(s) - missing permissions or they are not in voice')}"
        
        await ctx.send(success(message))

    @moveer.command(name="cmove")
    @commands.has_permissions(move_members=True)
    @commands.bot_has_permissions(move_members=True)
    async def cmove(self, ctx: commands.Context, target_channel: discord.VoiceChannel,
                    user1: discord.Member, user2: Optional[discord.Member] = None,
                    user3: Optional[discord.Member] = None,
                    user4: Optional[discord.Member] = None,
                    user5: Optional[discord.Member] = None,
                    user6: Optional[discord.Member] = None):
        """
        Move users to a specific voice channel.
        """
        users = [u for u in [user1, user2, user3, user4, user5, user6] if u is not None]
        connected_users = [u for u in users if self._is_connected_to_voice(u)]
        
        if not connected_users:
            await ctx.send(warning("None of the specified users are in voice channels."))
            return

        stats = await self._move_users_batch(ctx, connected_users, target_channel, "cmove")
        
        message = f"Moved {stats['moved']} user{'s' if stats['moved'] != 1 else ''} to {target_channel.mention}"
        if stats['failed'] > 0:
            message += f"\n{warning('Failed to move ' + str(stats['failed']) + ' user(s)')}"
        
        await ctx.send(success(message))

    @moveer.command(name="fmove")
    @commands.has_permissions(move_members=True)
    @commands.bot_has_permissions(move_members=True)
    async def fmove(self, ctx: commands.Context, from_channel: discord.VoiceChannel, 
                    to_channel: discord.VoiceChannel):
        """
        Move all users from one voice channel to another.
        """
        if from_channel.id == to_channel.id:
            await ctx.send(error("Source and target channels cannot be the same."))
            return

        users = list(from_channel.members)
        if not users:
            await ctx.send(warning(f"No users found in {from_channel.mention}."))
            return

        stats = await self._move_users_batch(ctx, users, to_channel, "fmove")
        
        message = f"Moved {stats['moved']} user{'s' if stats['moved'] != 1 else ''} from {from_channel.mention} to {to_channel.mention}"
        if stats['failed'] > 0:
            message += f"\n{warning('Failed to move ' + str(stats['failed']) + ' user(s)')}"
        
        await ctx.send(success(message))

    @moveer.command(name="amove")
    @commands.has_permissions(move_members=True)
    @commands.bot_has_permissions(move_members=True)
    async def amove(self, ctx: commands.Context):
        """
        Move all users from all voice channels to your current voice channel.
        """
        author_voice = self._get_user_voice_channel(ctx.author)
        if not author_voice:
            await ctx.send(error("You need to be in a voice channel to use this command."))
            return

        all_users = []
        for channel in ctx.guild.voice_channels:
            if channel.id != author_voice.id:
                all_users.extend(channel.members)

        if not all_users:
            await ctx.send(warning("No users found in other voice channels."))
            return

        stats = await self._move_users_batch(ctx, all_users, author_voice, "amove")
        
        message = f"Moved {stats['moved']} user{'s' if stats['moved'] != 1 else ''} to {author_voice.mention}"
        if stats['failed'] > 0:
            message += f"\n{warning('Failed to move ' + str(stats['failed']) + ' user(s)')}"
        
        await ctx.send(success(message))

    @moveer.command(name="tmove")
    @commands.has_permissions(move_members=True)
    @commands.bot_has_permissions(move_members=True)
    async def tmove(self, ctx: commands.Context, target_channel: discord.VoiceChannel,
                    role1: discord.Role, role2: Optional[discord.Role] = None,
                    role3: Optional[discord.Role] = None,
                    role4: Optional[discord.Role] = None,
                    role5: Optional[discord.Role] = None):
        """
        Move all users with specific roles to a voice channel.
        """
        roles = [r for r in [role1, role2, role3, role4, role5] if r is not None]
        users_to_move = []
        
        for role in roles:
            for member in role.members:
                if self._is_connected_to_voice(member) and member not in users_to_move:
                    users_to_move.append(member)

        if not users_to_move:
            await ctx.send(warning("No users with the specified roles are in voice channels."))
            return

        stats = await self._move_users_batch(ctx, users_to_move, target_channel, "tmove")
        
        message = f"Moved {stats['moved']} user{'s' if stats['moved'] != 1 else ''} with specified roles to {target_channel.mention}"
        if stats['failed'] > 0:
            message += f"\n{warning('Failed to move ' + str(stats['failed']) + ' user(s)')}"
        
        await ctx.send(success(message))

    @moveer.command(name="rmove")
    @commands.has_permissions(move_members=True)
    @commands.bot_has_permissions(move_members=True)
    async def rmove(self, ctx: commands.Context, role: discord.Role):
        """
        Move all users with a specific role to your voice channel.
        """
        author_voice = self._get_user_voice_channel(ctx.author)
        if not author_voice:
            await ctx.send(error("You need to be in a voice channel to use this command."))
            return

        users_to_move = []
        for member in role.members:
            if (self._is_connected_to_voice(member) and 
                member.id != ctx.author.id and 
                self._get_user_voice_channel(member) != author_voice):
                users_to_move.append(member)

        if not users_to_move:
            await ctx.send(warning(f"No users with role {role.mention} are in other voice channels."))
            return

        stats = await self._move_users_batch(ctx, users_to_move, author_voice, "rmove")
        
        message = f"Moved {stats['moved']} user{'s' if stats['moved'] != 1 else ''} with role {role.mention} to {author_voice.mention}"
        if stats['failed'] > 0:
            message += f"\n{warning('Failed to move ' + str(stats['failed']) + ' user(s)')}"
        
        await ctx.send(success(message))

    @moveer.command(name="ymove")
    @commands.has_permissions(move_members=True)
    @commands.bot_has_permissions(move_members=True)
    async def ymove(self, ctx: commands.Context, from_channel: discord.VoiceChannel,
                    target_category: discord.CategoryChannel, users_per_channel: int):
        """
        Spread users from one channel across multiple channels in a category.
        """
        if users_per_channel < 1:
            await ctx.send(error("Users per channel must be at least 1."))
            return

        # Get voice channels in the category
        target_channels = [ch for ch in target_category.voice_channels if ch.id != from_channel.id]
        if not target_channels:
            await ctx.send(error(f"No voice channels found in category {target_category.name}."))
            return

        users = list(from_channel.members)
        if not users:
            await ctx.send(warning(f"No users found in {from_channel.mention}."))
            return

        # Distribute users across channels
        moved_total = 0
        failed_total = 0
        
        for i, channel in enumerate(target_channels):
            start_idx = i * users_per_channel
            end_idx = start_idx + users_per_channel
            batch = users[start_idx:end_idx]
            
            if batch:
                stats = await self._move_users_batch(ctx, batch, channel, "ymove")
                moved_total += stats['moved']
                failed_total += stats['failed']

        message = f"Spread {moved_total} user{'s' if moved_total != 1 else ''} across {len(target_channels)} channels"
        if failed_total > 0:
            message += f"\n{warning('Failed to move ' + str(failed_total) + ' user(s)')}"
        
        await ctx.send(success(message))

    @moveer.command(name="dmove")
    @commands.has_permissions(move_members=True)
    @commands.bot_has_permissions(move_members=True)
    async def dmove(self, ctx: commands.Context, 
                    from_channel1: discord.VoiceChannel,
                    from_channel2: discord.VoiceChannel,
                    target_category: discord.CategoryChannel,
                    users_per_channel: int):
        """
        Spread users from two channels across multiple channels in a category.
        """
        if users_per_channel < 1:
            await ctx.send(error("Users per channel must be at least 1."))
            return

        target_channels = list(target_category.voice_channels)
        if not target_channels:
            await ctx.send(error(f"No voice channels found in category {target_category.name}."))
            return

        users1 = list(from_channel1.members)
        users2 = list(from_channel2.members)
        
        if not users1 and not users2:
            await ctx.send(warning("No users found in either source channel."))
            return

        # Take users from each channel
        users_to_move = users1[:users_per_channel] + users2[:users_per_channel]
        
        moved_total = 0
        failed_total = 0
        
        for i, channel in enumerate(target_channels):
            if i < len(users_to_move):
                stats = await self._move_users_batch(ctx, [users_to_move[i]], channel, "dmove")
                moved_total += stats['moved']
                failed_total += stats['failed']

        message = f"Spread {moved_total} user{'s' if moved_total != 1 else ''} from two channels across {len(target_channels)} channels"
        if failed_total > 0:
            message += f"\n{warning('Failed to move ' + str(failed_total) + ' user(s)')}"
        
        await ctx.send(success(message))

    @moveer.command(name="zmove")
    @commands.has_permissions(move_members=True)
    @commands.bot_has_permissions(move_members=True)
    async def zmove(self, ctx: commands.Context, 
                    source_category: discord.CategoryChannel,
                    target_channel: discord.VoiceChannel):
        """
        Move all users from a category to a specific channel.
        """
        users_to_move = []
        for channel in source_category.voice_channels:
            if channel.id != target_channel.id:
                users_to_move.extend(channel.members)

        if not users_to_move:
            await ctx.send(warning(f"No users found in category {source_category.name}."))
            return

        stats = await self._move_users_batch(ctx, users_to_move, target_channel, "zmove")
        
        message = f"Moved {stats['moved']} user{'s' if stats['moved'] != 1 else ''} from {source_category.name} to {target_channel.mention}"
        if stats['failed'] > 0:
            message += f"\n{warning('Failed to move ' + str(stats['failed']) + ' user(s)')}"
        
        await ctx.send(success(message))

    @moveer.command(name="ckick")
    @commands.has_permissions(move_members=True)
    @commands.bot_has_permissions(move_members=True)
    async def ckick(self, ctx: commands.Context, user: discord.Member):
        """
        Disconnect a specific user from voice.
        """
        if not self._is_connected_to_voice(user):
            await ctx.send(warning(f"{user.mention} is not in a voice channel."))
            return

        try:
            await user.move_to(None)
            await ctx.send(success(f"Disconnected {user.mention} from voice."))
            
            # Update statistics
            async with self.config.statistics() as stats:
                stats["total_disconnects"] += 1
                if "ckick" not in stats["commands_used"]:
                    stats["commands_used"]["ckick"] = 0
                stats["commands_used"]["ckick"] += 1
                
        except discord.HTTPException:
            await ctx.send(error(f"Missing permissions to disconnect {user.mention} from voice."))

    @moveer.command(name="fkick")
    @commands.has_permissions(move_members=True)
    @commands.bot_has_permissions(move_members=True)
    async def fkick(self, ctx: commands.Context, channel: discord.VoiceChannel):
        """
        Disconnect all users from a specific voice channel.
        """
        users = list(channel.members)
        if not users:
            await ctx.send(warning(f"No users found in {channel.mention}."))
            return

        moved = 0
        failed = 0
        
        for user in users:
            try:
                await user.move_to(None)
                moved += 1
                await asyncio.sleep(0.1)  # Rate limiting
            except discord.HTTPException:
                failed += 1

        message = f"Disconnected {moved} user{'s' if moved != 1 else ''} from {channel.mention}"
        if failed > 0:
            message += f"\n{warning('Failed to disconnect ' + str(failed) + ' user(s)')}"
        
        await ctx.send(success(message))
        
        # Update statistics
        async with self.config.statistics() as stats:
            stats["total_disconnects"] += moved
            if "fkick" not in stats["commands_used"]:
                stats["commands_used"]["fkick"] = 0
            stats["commands_used"]["fkick"] += 1

    @moveer.command(name="zkick")
    @commands.has_permissions(move_members=True)
    @commands.bot_has_permissions(move_members=True)
    async def zkick(self, ctx: commands.Context, category: discord.CategoryChannel):
        """
        Disconnect all users from all voice channels in a category.
        """
        users_to_kick = []
        for channel in category.voice_channels:
            users_to_kick.extend(channel.members)

        if not users_to_kick:
            await ctx.send(warning(f"No users found in category {category.name}."))
            return

        moved = 0
        failed = 0
        
        for user in users_to_kick:
            try:
                await user.move_to(None)
                moved += 1
                await asyncio.sleep(0.1)  # Rate limiting
            except discord.HTTPException:
                failed += 1

        message = f"Disconnected {moved} user{'s' if moved != 1 else ''} from {category.name}"
        if failed > 0:
            message += f"\n{warning('Failed to disconnect ' + str(failed) + ' user(s)')}"
        
        await ctx.send(success(message))
        
        # Update statistics
        async with self.config.statistics() as stats:
            stats["total_disconnects"] += moved
            if "zkick" not in stats["commands_used"]:
                stats["commands_used"]["zkick"] = 0
            stats["commands_used"]["zkick"] += 1

    @moveer.command(name="ucount")
    async def ucount(self, ctx: commands.Context, channel: discord.VoiceChannel):
        """
        Count the number of users in a voice channel.
        """
        user_count = len(channel.members)
        await ctx.send(info(f"There { 'are' if user_count != 1 else 'is' } {user_count} user{'s' if user_count != 1 else ''} in {channel.mention}."))

    @moveer.command(name="stats")
    @commands.is_owner()
    async def stats(self, ctx: commands.Context):
        """
        Show usage statistics for the Moveer cog.
        """
        statistics = await self.config.statistics()
        
        embed = discord.Embed(
            title="Moveer Statistics",
            color=discord.Color.blue()
        )
        
        embed.add_field(name="Total Moves", value=statistics["total_moves"], inline=True)
        embed.add_field(name="Total Disconnects", value=statistics["total_disconnects"], inline=True)
        
        commands_text = "\n".join([f"• {cmd}: {count}" for cmd, count in statistics["commands_used"].items()])
        embed.add_field(name="Command Usage", value=commands_text or "No commands used yet", inline=False)
        
        await ctx.send(embed=embed)

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
