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
        "gamechannels": {}
    }

    def __init__(self, bot: Red) -> None:
        """Set up the cog."""
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=1884366863, force_registration=True
        )
        self.config.register_global(**self.default_global_settings)
        # self.config.register_guild(**self.default_guild_settings)
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

    @commands.command(name="gchan", description="Set Game Channel")
    async def set_gamechannel(self, ctx, channel: int, game: str):
        if member:
            owner = await self.bot.is_owner(ctx.author)
            if not owner: return
            ctx.author = member
        try:
            dt_birthday = self._parse_date(date)
            birthdays = await self.config.birthdays()
            birthdays[ctx.author.id] = str(dt_birthday)
            await self.config.birthdays.set(birthdays)
            dt_next = self._get_next(dt_birthday)
            await self._create_event(ctx, dt_next)
            await ctx.reply(lang.get("response.birthday_set").format(month=dt_birthday.month,day=dt_birthday.day))
        except ValueError as err:
            log.error(err)
            await ctx.reply(lang.get("response.invalid_date_format"))
            
# endregion metods

# region events
    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState
    ):
        # Check if the update involves joining the specified voice channel
        target_channel_id = 1366803519511859252
        if after.channel and after.channel.id == target_channel_id:
            # Get the member's current activity
            activities = [
                activity.application_id 
                for activity in member.activities 
                if isinstance(activity, discord.Activity)
            ]
            
            # Check if the required game is being played
            required_game_id = "1306357637893587014"
            if required_game_id not in activities:
                # Send DM explaining why they're being moved
                try:
                    await member.send(
                        "You were removed from the voice channel because you weren't "
                        "playing the required game."
                    )
                except discord.Forbidden:
                    # Handle cases where DMs aren't possible
                    pass
                
                # Move the member to a default channel (or disconnect them)
                default_channel = member.guild.afk_channel
                if default_channel:
                    await member.move_to(default_channel)
                else:
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
