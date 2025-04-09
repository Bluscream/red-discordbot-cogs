"""BanCheck cog for Red-DiscordBot ported and enhanced by PhasecoreX."""

from contextlib import suppress
from typing import Any, ClassVar
from datetime import date, datetime

import discord, pytz, json, os
from discord.ext import tasks # commands
from redbot.core import Config, checks, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import error, info, success, warning

from .pcx_lib import *

from strings import Strings
lang = Strings('de')


class Birthdays(commands.Cog):
    """
    """

    __author__ = "Bluscream"
    __version__ = "1.0.0"

    default_global_settings: ClassVar[dict[str, int] | dict[str, dict[str, str]]] = {
        "schema_version": 0,
        "birthdays": {}
    }

    def __init__(self, bot: Red) -> None:
        """Set up the cog."""
        super().__init__()
        self.bot = bot
        self.birthday_data = {} # replace
        self.config = Config.get_conf(
            self, identifier=1884366860, force_registration=True
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
        """Nothing to delete."""
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
    def _parse_birthday(self, date_str):
        """Parse birthday date string in various formats"""
        try:
            # Try ISO format first (YYYY-MM-DD)
            return date.fromisoformat(date_str)
        except ValueError:
            try:
                # Try MM-DD format
                month, day = map(int, date_str.split('-'))
                return date(2024, month, day)
            except ValueError:
                raise ValueError(lang.get("error.invalid_date_format").format(date_str=date_str))


    # @commands.command(name="ping", help="Check the bot's latency")
    # async def ping(self, ctx):
    #     latency = self.bot.latency * 1000  # Convert to milliseconds
    #     await ctx.send(lang.get("response.ping").format(latency=f"{latency:.2f}"))

    @commands.command(name="bday", description="Set your birthday")
    async def set_birthday(self, ctx, day: int, month: int):
        if not (1 <= month <= 12 and 1 <= day <= 31):
            await ctx.send(lang.get("response.invalid_date_format"))
            return
            
        try:
            current_year = datetime.now().year + 1
            dt = date(current_year, month, day)
            start = pytz.utc.localize(datetime.combine(dt, datetime.min.time()))
            end = pytz.utc.localize(datetime.combine(dt, datetime.max.time()))
            
            guild_id = str(ctx.guild.id)
            member_id = str(ctx.author.id)
            
            if guild_id not in self.birthday_data:
                self.birthday_data[guild_id] = {"members": {}}
            iso_date = f"{current_year}-{month:02d}-{day:02d}"
            self.birthday_data[guild_id]["members"][member_id] = {
                "date": iso_date,
                "username": ctx.author.name,
                # "discriminator": ctx.author.discriminator
            }
            
            with open("birthdays.json", "w") as f:
                json.dump(self.birthday_data, f)

            # set in red config
            birthdays = await self.config.birthdays()
            birthdays[member_id] = start
            await self.config.birthdays.set(birthdays)

            event_name = lang.get("event.name").format(username=ctx.author.name,guild_name=ctx.guild.name)

            event_exists = False
            for event in ctx.guild.scheduled_events:
                if event.name == event_name:
                    event_exists = True
                    break
            
            if not event_exists:
                event = await ctx.guild.create_scheduled_event(
                    name=event_name,
                    description=lang.get("event.description").format(username=ctx.author.name,guild_name=ctx.guild.name),
                    start_time=start,
                    end_time=end,
                    privacy_level=discord.PrivacyLevel.guild_only,
                    location=lang.get("event.location").format(username=ctx.author.name,guild_name=ctx.guild.name),
                    entity_type=discord.EntityType.external,
                    reason=lang.get("event.reason").format(botname=self.bot.user)
                )
                await ctx.send(lang.get("response.event_created"))
                
            await ctx.send(lang.get("response.birthday_set").format(month=month,day=day))
            
        except ValueError as err:
            print(err)
            await ctx.send(lang.get("response.invalid_date_format"))

    @commands.command(name="listbdays", description="List upcoming birthdays")
    async def list_birthdays(self, ctx):
        guild_id = str(ctx.guild.id)
        
        if guild_id not in self.birthday_data:
            await ctx.send(lang.get("response.no_birthdays"))
            return
            
        today = date.today()
        upcoming_birthdays = []
        
        for member_id, birthday_data in self.birthday_data[guild_id]["members"].items():
            try:
                bday_date = self._parse_birthday(birthday_data["date"])
                
                # Calculate days until birthday
                next_birthday = date(today.year, bday_date.month, bday_date.day)
                if next_birthday < today:
                    next_birthday = date(today.year + 1, bday_date.month, bday_date.day)
                
                days_until = (next_birthday - today).days
                
                username = f"{birthday_data['username']}#{birthday_data['discriminator']}"

                upcoming_birthdays.append(lang.get("response.days_until_birthday").format(username=username,days_until=days_until))
            except ValueError as err:
                print(lang.get("error.skipping_invalid_birthday").format(username=birthday_data['username'],err=err))
        
        if not upcoming_birthdays:
            await ctx.send(lang.get("response.no_upcoming_birthdays"))
        else:
            await ctx.send("\n".join(upcoming_birthdays))
# endregion metods

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
