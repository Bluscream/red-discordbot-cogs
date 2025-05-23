"""BanCheck cog for Red-DiscordBot ported and enhanced by PhasecoreX."""

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

log = getLogger("red.blu.birthdays")

from .strings import Strings
lang = Strings('de')

date_formats = [
    "%d.%m.%y",  # 1.12.95
    "%d.%m.%Y",  # 1.12.1995
    "%Y-%m-%d",  # 1995-12-01
    "%d.%m.",    # 1.12.
    "%d %m",    # 1 12
    "%d %m %y",    # 1 12 95
    "%d %m %Y",    # 1 12 1995
    "%d-%m-%y",  # 1-12-95
    "%d-%m-%Y",  # 1-12-1995
    "%d/%m/%y",  # 1/12/95
    "%d/%m/%Y",  # 1/12/1995
]

emojis = ['🎂','🎉','🧁','🥂','🍻','🍾','🎈','🎁','🎊']


class Birthdays(commands.Cog):
    """
    """

    __author__ = "Bluscream"
    __version__ = "1.0.0"

    default_global_settings: ClassVar[dict[str, int] | dict[str, dict[int, str]]] = {
        "schema_version": 0,
        "birthdays": {}
    }

    def __init__(self, bot: Red) -> None:
        """Set up the cog."""
        super().__init__()
        self.bot = bot
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
    def _parse_date(self, date_str):
        """Parse birthday date string in various formats"""
        for fmt in date_formats:
            try:
                if fmt.endswith("."):
                    date_sep = "" if date_str.endswith(".") else "."
                    date_str = date_str + date_sep + str(datetime.now().year)
                    fmt = fmt + "%Y"
                elif fmt.endswith("-"):
                    date_sep = "" if date_str.endswith("-") else "-"
                    date_str = date_str + date_sep + str(datetime.now().year)
                    fmt = fmt + "%Y"
                parsed_date = datetime.strptime(date_str, fmt)
                return parsed_date.date()
            except ValueError:
                continue
        raise ValueError(lang.get("error.invalid_date_format").format(date_str=date_str))

    def _get_next(self, dt: date):
        now = datetime.now().date()
        if isinstance(dt, datetime): dt = dt.date()
        # log.error(f"dt: {dt}, dt <= now: {dt <= now}, now: {now}")
        if dt <= now: # If the date is in the past, add a year to make it next year's date
            dt = date(now.year + 1, dt.month, dt.day)
        elif dt > date(now.year + 1, now.month, now.day): # If the date is in the future but more than a year away, set to current year
            dt = date(now.year, dt.month, dt.day)
        return dt

    async def _create_event(self, ctx, dt: date):
        """"""
        # Do dt_next here?
        start = pytz.utc.localize(datetime.combine(dt, datetime.min.time()))
        end = pytz.utc.localize(datetime.combine(dt, datetime.max.time()))
        event_name = lang.get("event.name").format(username=ctx.author.name,nickname=ctx.author.nick or ctx.author.global_name,guild_name=ctx.guild.name)
        event_exists = False
        for event in ctx.guild.scheduled_events:
            if event.name == event_name:
                await event.delete(reason=lang.get("reason.event_recreate").format(username=ctx.author.name,nickname=ctx.author.nick or ctx.author.global_name,guild_name=ctx.guild.name,botname=self.bot.user))
        prefix = f"{choice(emojis)}  " if choice([True, False]) else ""
        suffix = f"  {choice(emojis)}" if choice([True, False]) else ""
        description = lang.get(f"event.description{randint(1, 10)}").format(username=ctx.author.name,nickname=ctx.author.nick or ctx.author.global_name,guild_name=ctx.guild.name)
        return await ctx.guild.create_scheduled_event(
            name=event_name,
            description=f"{prefix}{description}{suffix}\n\n||birthday:{ctx.author.id}||",
            start_time=start,
            end_time=end,
            privacy_level=discord.PrivacyLevel.guild_only,
            location=lang.get("event.location").format(username=ctx.author.name,nickname=ctx.author.nick or ctx.author.global_name,guild_name=ctx.guild.name),
            entity_type=discord.EntityType.external,
            reason=lang.get("reason.event_create").format(botname=self.bot.user)
        )

    @commands.command(name="rbdays", description="Recreate all birthday events")
    @commands.is_owner()
    async def recreate_birthdays(self, ctx):
        _cnt = 0
        events = ctx.guild.scheduled_events
        for event in events:
            if not event.name.startswith(lang.get("event.name").split()[0]): continue
            ctx.author = discord.utils.get(ctx.guild.members, name=event.name.split()[-1])
            birthdays = await self.config.birthdays()
            if not ctx.author.id in birthdays:
                birthdays[ctx.author.id] = str(event.start_time.date())
                await self.config.birthdays.set(birthdays)
            dt_birthday = self._parse_date(birthdays[ctx.author.id])
            dt_next = self._get_next(dt_birthday)
            await self._create_event(ctx, dt_next)
            _cnt += 1
            await asyncio.sleep(1)
        await ctx.respond(lang.get("response.finished_recreate").format(count=_cnt, events=len(events)))

    @commands.command(name="bday", description="Set your birthday")
    async def set_birthday(self, ctx, date: str, member: discord.Member = None):
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
            
    @commands.command(name="bdays", description="List all saved birthdays and days until next birthday")
    async def list_birthdays(self, ctx):
        birthdays = await self.config.birthdays()
        if not birthdays:
            await ctx.reply(lang.get("response.no_birthdays"))
            return
        today = datetime.now().date()
        upcoming_birthdays = []
        for user_id, date_str in birthdays.items():
            member = ctx.guild.get_member(int(user_id))
            if not member:
                continue
            dt_birthday = datetime.strptime(date_str, "%Y-%m-%d")
            dt_next = self._get_next(dt_birthday)
            days_until = (dt_next - today).days
            birthday_str = dt_birthday.strftime('%d.%m.') if dt_birthday.year >= today.year else dt_birthday.strftime('%d.%m.%Y')
            upcoming_birthdays.append((days_until, member, birthday_str))
        if not upcoming_birthdays:
            await ctx.reply(lang.get("response.no_upcoming_birthdays"))
            return
        upcoming_birthdays.sort()
        response = lang.get("title.upcoming_birthdays").format(birthdays=len(upcoming_birthdays))
        response += "\n".join(
            lang.get("response.days_until_birthday").format(nickname=member.nick or member.global_name or member.name, birthday=birthday_str, days=days)
            for days, member, birthday_str in upcoming_birthdays
        )
        await ctx.reply(response)
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
