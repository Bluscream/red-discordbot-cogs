"""BanCheck cog for Red-DiscordBot ported and enhanced by PhasecoreX."""

from contextlib import suppress
from typing import Any, ClassVar
from datetime import date, datetime

import discord, pytz, json, os
# from discord.ext import commands, tasks
from redbot.core import Config, checks, commands, tasks
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


    # stuff

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
