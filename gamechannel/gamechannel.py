"""GameChannel cog for Red-DiscordBot"""

from contextlib import suppress
from typing import Any, ClassVar
from datetime import date, datetime
from logging import getLogger
from random import randint, choice

import discord, pytz, os
from discord.ext import tasks # commands
from redbot.core import Config, checks, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import error, info, success, warning

from .pcx_lib import *

log = getLogger("red.blu.gamechannel")

from .strings import Strings
lang = Strings('de')


class GameChannel(commands.Cog):
    """
    """

    __author__ = "Bluscream"
    __version__ = "1.0.0"

    default_global_settings: ClassVar[dict[str, int] | dict[str, dict[int, str]]] = {
        "schema_version": 0,
        "channels": {}
    }

    default_guild_settings: ClassVar[dict[int, str]] = {
        "channels": {}
    }

    def __init__(self, bot: Red) -> None:
        """Set up the cog."""
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=1884366863, force_registration=True
        )
        self.config.register_global(**self.default_global_settings)
        self.config.register_guild(**self.default_guild_settings)
        self.bucket_member_join_cache = commands.CooldownMapping.from_cooldown(
            1, 300, lambda member: member
        )

    #
    # Red methods
    #

    def format_help_for_context(self, ctx: commands.Context) -> str:
        """Show version in help."""
        pre_processed = super().format_help_for_context(ctx)
        return f"{pre_processed}\n\nCog Version: {self.__version__}"

    async def red_delete_data_for_user(self, *, _requester: str, _user_id: int) -> None:
        birthdays = await self.config.birthdays()
        if _user_id in birthdays:
            del birthdays[ctx.author.id]
            await self.config.birthdays.set(birthdays)
        return

    #
    # Initialization methods
    #

    async def initialize(self) -> None:
        """Perform setup actions before loading cog."""
        await self._migrate_config()

    async def _migrate_config(self) -> None:
        """Perform some configuration migrations."""
        schema_version = await self.config.schema_version()


# region methods

# lang.get("response.birthday_set").format(month=dt_birthday.month,day=dt_birthday.day)

    @checks.admin_or_permissions(manage_channels=True)
    @commands.group(name="gamechannel", aliases=["gc"])
    async def game_channel(self, ctx: commands.Context):
        """Manage voice channel game requirements."""
        pass

    @game_channel.command(name="set")
    async def set_gamechannel(self, ctx: commands.Context, channel: discord.VoiceChannel, game_id: str = None):
        """Set a required game for a voice channel."""
        if not game_id: return await self.remove_gamechannel(self, ctx, channel)
        async with self.config.guild(ctx.guild).channels() as channels:
            channels[str(channel.id)] = game_id
        
        await ctx.send(
            f"Set game requirement for {channel.mention}: "
            f"Application ID {game_id}"
        )

    @game_channel.command(name="remove")
    async def remove_gamechannel(self, ctx: commands.Context, channel: discord.VoiceChannel):
        """Remove game requirement from a voice channel."""
        async with self.config.guild(ctx.guild).channels() as channels:
            if str(channel.id) in channels:
                del channels[str(channel.id)]
                await ctx.send(f"Removed game requirement from {channel.mention}")
            else:
                await ctx.send(
                    f"No game requirement set for {channel.mention}"
                )

    @game_channel.command(name="check")
    async def gamechannel_check(self, ctx: commands.Context):
        """Check all users in game-restricted voice channels and remove those not playing the required game."""
        if not ctx.guild:
            await ctx.send("This command can only be used in a server.")
            return
        
        removed_users = 0
        checked_channels = 0
        
        # Get all guilds if command is used by bot owner, otherwise just the current guild
        guilds = self.bot.guilds if await self.bot.is_owner(ctx.author) else [ctx.guild]
        
        status_message = await ctx.send("Checking voice channels for users not playing required games...")
        
        for guild in guilds:
            channels = await self.config.guild(guild).channels()
            if not channels:
                continue
                
            for channel_id, required_game_id in channels.items():
                channel = guild.get_channel(int(channel_id))
                if not channel or not isinstance(channel, discord.VoiceChannel):
                    continue
                    
                checked_channels += 1
                
                for member in channel.members:
                    activities = [
                        str(activity.application_id) 
                        for activity in member.activities 
                        if isinstance(activity, discord.Activity) and activity.application_id
                    ]
                    
                    if required_game_id not in activities:
                        try:
                            await member.send(f"You were removed from {channel.mention} because you weren't playing the required game.")
                        except discord.Forbidden:
                            pass
                            
                        try:
                            await member.edit(voice_channel=None)
                            removed_users += 1
                        except discord.Forbidden:
                            log.warning(f"Could not remove {member} from {channel} in {guild} due to permissions.")
        
        await status_message.delete()
        await ctx.send(
            f"Check complete! Checked {checked_channels} channels across {len(guilds)} "
            f"servers and removed {removed_users} users not playing required games."
        )

    @game_channel.command(name="list")
    async def gamechannel_list(self, ctx: commands.Context):
        """List all voice channels with game requirements."""
        if not ctx.guild:
            await ctx.send("This command can only be used in a server.")
            return
        channels = await self.config.guild(ctx.guild).channels()
        if not channels:
            await ctx.send("No voice channels have game requirements set.")
            return
        
        embed = discord.Embed(title="Voice Channel Game Requirements")
        for channel_id, game_id in channels.items():
            channel = ctx.guild.get_channel(int(channel_id))
            if channel:
                embed.add_field(
                    name=f"{channel.mention}",
                    value=f"Required Game ID: {game_id}",
                    inline=False
                )
        await ctx.send(embed=embed)
            
# endregion metods

# region events
    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState
    ):
        if not after.channel:
            return

        guild_config = self.config.guild(member.guild)
        channels = await guild_config.channels()
        
        if str(after.channel.id) not in channels:
            return

        required_game_id = channels[str(after.channel.id)]
        
        activities = [
            activity.application_id 
            for activity in member.activities 
            if isinstance(activity, discord.Activity)
        ]
        
        if required_game_id not in activities:
            try:
                await member.send(f"You were removed from {after.channel.mention} because you weren't playing the required game.")
            except discord.Forbidden:
                pass

            # Move the member to a default channel (or disconnect them)
            # default_channel = member.guild.afk_channel
            # if default_channel:
            #     await member.move_to(default_channel)
            # else:
            await member.edit(voice_state=None)
# endregion events

    @staticmethod
    async def send_embed(
        channel_or_ctx: commands.Context | discord.TextChannel,
        embed: discord.Embed,
    ) -> bool:
        """Send an embed. If the bot can't send it, complains about permissions."""
        destination = (
            channel_or_ctx.channel
            if isinstance(channel_or_ctx, commands.Context)
            else channel_or_ctx
        )
        if (
            hasattr(destination, "guild")
            and destination.guild
            and not destination.permissions_for(destination.guild.me).embed_links
        ):
            await destination.send(
                error("I need the `Embed links` permission to function properly")
            )
            return False
        await destination.send(embed=embed)
        return True

    @staticmethod
    def embed_maker(
        title: str | None,
        color: discord.Colour | None,
        description: str | None,
        avatar: str | None = None,
    ) -> discord.Embed:
        """Create a nice embed."""
        embed = discord.Embed(title=title, color=color, description=description)
        if avatar:
            embed.set_thumbnail(url=avatar)
        return embed
