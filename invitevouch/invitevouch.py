"""One-by-one vouched single-use invite system for Red-DiscordBot."""

import logging
from datetime import UTC, datetime
from typing import Any

import discord
from discord import app_commands
from redbot.core import Config, checks, commands
from redbot.core.bot import Red

log = logging.getLogger("red.blu.invitevouch")
MESSAGE_LIMIT = 2000


class InviteModal(discord.ui.Modal, title="Einladung anfordern / Request Invite"):
    """Form asking who should be invited and why."""

    target_name: discord.ui.TextInput["InviteModal"] = discord.ui.TextInput(
        label="Wen möchtest du einladen? / Person's name",
        placeholder="Discord-Name oder Handle der Person (z. B. Max oder @username)",
        min_length=2,
        max_length=100,
        required=True,
    )
    reason: discord.ui.TextInput["InviteModal"] = discord.ui.TextInput(
        label="Grund für die Einladung / Reason",
        style=discord.TextStyle.paragraph,
        placeholder="Warum möchtest du diese Person einladen? Wie gut kennst du sie?",
        min_length=5,
        max_length=1000,
        required=True,
    )

    def __init__(self, cog: "InviteVouch") -> None:
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Check the allowance, create a single-use invite and log it."""
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message(
                "Nur auf Servern verfügbar.", ephemeral=True
            )
            return

        conf = self.cog.config.guild(guild)
        channel_id = await conf.invite_channel_id()
        channel = (
            guild.get_channel(channel_id)
            if channel_id
            else (guild.rules_channel or guild.system_channel)
        )
        if not channel or not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "❌ Kein gültiger Einladungskanal konfiguriert. Bitte wende dich an ein Team-Mitglied.",
                ephemeral=True,
            )
            return

        # Check bot permissions
        me = guild.me
        perms = channel.permissions_for(me)
        if not perms.create_instant_invite:
            await interaction.response.send_message(
                "❌ Dem Bot fehlt die Berechtigung, Einladungen in diesem Kanal zu erstellen.",
                ephemeral=True,
            )
            return

        target = self.target_name.value.strip()
        reason_text = self.reason.value.strip()
        user = interaction.user

        # Per-member limit: used invites and still-valid pending ones both count.
        limit = await conf.max_per_member()
        is_staff = isinstance(user, discord.Member) and await self.cog.bot.is_mod(user)
        if limit > 0 and not is_staff:
            taken = self.cog.count_slots(await conf.invites(), user.id)
            if taken >= limit:
                await interaction.response.send_message(
                    f"❌ Du hast dein Einladungs-Kontingent ({limit}) bereits genutzt. "
                    "Ein Team-Mitglied kann es bei Bedarf zurücksetzen.\n"
                    f"You already used your invite allowance ({limit}). Staff can reset it if needed.",
                    ephemeral=True,
                )
                return

        try:
            # Create single-use invite (max_uses=1, unique=True, 7 days expiration)
            invite = await channel.create_invite(
                max_uses=1,
                max_age=86400 * 7,
                unique=True,
                reason=f"InviteVouch by {user} (ID: {user.id}) for {target}: {reason_text[:60]}",
            )
        except Exception:
            log.exception("Failed to create single-use invite for %s", user)
            await interaction.response.send_message(
                "❌ Fehler beim Erstellen der Einladung. Bitte versuche es später noch einmal.",
                ephemeral=True,
            )
            return

        # Update cache
        if guild.id not in self.cog.invites_cache:
            self.cog.invites_cache[guild.id] = {}
        self.cog.invites_cache[guild.id][invite.code] = 0

        # Save record to config
        now_iso = datetime.now(UTC).isoformat()
        inv_record = {
            "code": invite.code,
            "url": invite.url,
            "inviter_id": user.id,
            "inviter_name": str(user),
            "target_name": target,
            "reason": reason_text,
            "created_at": now_iso,
            "channel_id": channel.id,
            "used": False,
            "joined_user_id": None,
            "joined_at": None,
        }
        async with conf.invites() as inv_dict:
            inv_dict[invite.code] = inv_record

        # Ephemeral confirmation to user
        user_embed = discord.Embed(
            title="✉️ Dein persönlicher Einladungslink",
            description=(
                f"Dein 1-Person-Einladungslink wurde erfolgreich generiert:\n\n"
                f"🔗 **{invite.url}**\n\n"
                f"• **Für:** `{target}`\n"
                f"• **Gültigkeit:** Genau 1 Beitritt (max. 7 Tage)\n\n"
                f"> ⚠️ **Wichtig:** Bitte gib diesen Link **nur persönlich** an `{target}` weiter. "
                f"Einladungslinks dürfen nicht öffentlich geteilt werden. Jeder Beitritt wird protokolliert."
            ),
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=user_embed, ephemeral=True)

        # Audit log to server log channel (English only for internal logs)
        log_channel_id = await conf.log_channel_id()
        log_channel = guild.get_channel(log_channel_id) if log_channel_id else None
        if log_channel and isinstance(log_channel, discord.TextChannel):
            log_embed = discord.Embed(
                title="✉️ New Invite Issued",
                color=discord.Color.blue(),
                timestamp=datetime.now(UTC),
            )
            log_embed.add_field(
                name="Inviter",
                value=f"{user.mention} (`{user.name}` / `{user.id}`)",
                inline=False,
            )
            log_embed.add_field(
                name="Vouched For (Target)", value=f"`{target}`", inline=True
            )
            log_embed.add_field(
                name="Invite Code", value=f"`{invite.code}` ({invite.url})", inline=True
            )
            log_embed.add_field(
                name="Reason", value=f"```{reason_text}```", inline=False
            )
            log_embed.set_footer(
                text=f"Landing Channel: #{channel.name} · Max uses: 1 · Expires in 7d"
            )
            try:
                await log_channel.send(embed=log_embed)
            except Exception:
                log.exception("Failed to post invite log to #%s", log_channel.name)


class InviteButtonView(discord.ui.View):
    """Persistent panel button that opens the invite form."""

    def __init__(self, cog: "InviteVouch") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Einladung anfordern",
        style=discord.ButtonStyle.primary,
        custom_id="invitevouch:request_btn",
        emoji="✉️",
    )
    async def request_invite(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button["InviteButtonView"],
    ) -> None:
        """Open the invite request form."""
        await interaction.response.send_modal(InviteModal(self.cog))


class InviteVouch(commands.Cog):
    """Vouched single-use invite system with modals and logging."""

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=1567119401499762791, force_registration=True
        )
        default_guild = {
            "invite_channel_id": 1567164000976769025,  # #information
            "log_channel_id": 1567178000192245831,  # #⚙️server
            "member_log_channel_id": 1567177989286797446,  # #👥members
            "panel_channel_id": 1567200988178161805,  # #🎫create-ticket
            "panel_message_id": 0,
            "max_per_member": 1,  # 0 = unlimited; staff (Red mod/admin) are exempt
            "invites": {},
        }
        self.config.register_guild(**default_guild)
        self.invites_cache: dict[int, dict[str, int]] = {}
        self._button_view: InviteButtonView | None = None

    async def cog_load(self) -> None:
        """Register the persistent button and cache current invites."""
        self._button_view = InviteButtonView(self)
        self.bot.add_view(self._button_view)
        await self._populate_invite_cache()

    async def cog_unload(self) -> None:
        """Stop the persistent button view."""
        if self._button_view:
            self._button_view.stop()

    async def _populate_invite_cache(self) -> None:
        for guild in self.bot.guilds:
            try:
                me = guild.me
                if me.guild_permissions.manage_guild:
                    invs = await guild.invites()
                    self.invites_cache[guild.id] = {
                        inv.code: inv.uses or 0 for inv in invs
                    }
            except discord.HTTPException as e:
                log.warning("Could not cache invites for guild %s: %s", guild.id, e)

    @app_commands.command(
        name="invite",
        description="Fordere einen persönlichen 1-Person-Einladungslink an / Request a 1-time invite",
    )
    async def slash_invite(self, interaction: discord.Interaction) -> None:
        """Open the invite request form."""
        await interaction.response.send_modal(InviteModal(self))

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """Find which tracked invite was used and log the join."""
        guild = member.guild
        me = guild.me
        if not me.guild_permissions.manage_guild:
            return

        old_invs = self.invites_cache.get(guild.id, {})
        try:
            current_invs = {inv.code: inv.uses or 0 for inv in await guild.invites()}
        except Exception:
            log.exception("Failed to fetch invites on join for %s", member)
            return

        # Find which invite code was used
        used_code: str | None = None
        # 1. Did an existing invite increment its count?
        for code, old_uses in old_invs.items():
            if code in current_invs and current_invs[code] > old_uses:
                used_code = code
                break
        # 2. Or was a 1-use invite deleted upon joining?
        if not used_code:
            for code in old_invs:
                if code not in current_invs:
                    used_code = code
                    break

        # Update cache
        self.invites_cache[guild.id] = current_invs

        if not used_code:
            return

        # Check if code is in our database
        conf = self.config.guild(guild)
        invites = await conf.invites()
        if used_code not in invites:
            return

        # Update record
        now_iso = datetime.now(UTC).isoformat()
        record = invites[used_code]
        record["used"] = True
        record["joined_user_id"] = member.id
        record["joined_at"] = now_iso
        async with conf.invites() as inv_dict:
            inv_dict[used_code] = record

        # Log to member log channel (English only for internal logs)
        member_log_id = await conf.member_log_channel_id()
        log_channel = guild.get_channel(member_log_id) or guild.get_channel(
            await conf.log_channel_id()
        )
        if log_channel and isinstance(log_channel, discord.TextChannel):
            log_embed = discord.Embed(
                title="📥 Member Joined via Vouched Invite",
                description=f"{member.mention} (`{member.name}` / `{member.id}`) joined the server.",
                color=discord.Color.green(),
                timestamp=datetime.now(UTC),
            )
            log_embed.add_field(
                name="Invited By",
                value=f"<@{record['inviter_id']}> (`{record['inviter_name']}`)",
                inline=True,
            )
            log_embed.add_field(
                name="Vouched For (Target Name)",
                value=f"`{record['target_name']}`",
                inline=True,
            )
            log_embed.add_field(name="Invite Code", value=f"`{used_code}`", inline=True)
            log_embed.add_field(
                name="Original Reason", value=f"```{record['reason']}```", inline=False
            )
            try:
                await log_channel.send(embed=log_embed)
            except Exception:
                log.exception("Failed to post join log to #%s", log_channel.name)

    @commands.group(name="invitevouch")
    @checks.admin_or_permissions(manage_guild=True)
    async def invitevouch(self, ctx: commands.Context) -> None:
        """Manage the vouched 1-time invite system."""

    @invitevouch.command(name="panel")
    async def post_panel(
        self, ctx: commands.Context, channel: discord.TextChannel | None = None
    ) -> None:
        """Post the invite request panel message with the interactive button."""
        target_chan = channel or ctx.channel
        embed = discord.Embed(
            title="✉️ Einladung anfordern / Request Invite",
            description=(
                "🇩🇪 **Einladungen auf Vertrauensbasis**\n"
                "Jedes Mitglied darf Personen auf persönliche Vertrauensbasis einladen. "
                "Einladungslinks sind personengebunden und für genau **1 Beitritt** gültig.\n\n"
                "Klicke unten auf den Button, um das Formular auszufüllen (Name der Person & Grund). "
                "Der Bot generiert dir anschließend sofort deinen persönlichen Einladungslink.\n\n"
                "🇬🇧 **Vouched 1-Time Invites**\n"
                "Members may invite people they personally know and vouch for. "
                "Invite links are single-use.\n\n"
                "Click the button below to fill in the target name and reason to generate your link."
            ),
            color=discord.Color.blurple(),
        )
        view = InviteButtonView(self)
        msg = await target_chan.send(embed=embed, view=view)
        await self.config.guild(ctx.guild).panel_channel_id.set(target_chan.id)
        await self.config.guild(ctx.guild).panel_message_id.set(msg.id)
        await ctx.tick()

    @invitevouch.command(name="logchannel")
    async def set_log_channel(
        self, ctx: commands.Context, channel: discord.TextChannel
    ) -> None:
        """Set the channel where invite creations are logged."""
        await self.config.guild(ctx.guild).log_channel_id.set(channel.id)
        await ctx.send(f"✅ Invite log channel set to {channel.mention}.")

    @invitevouch.command(name="memberlog")
    async def set_member_log_channel(
        self, ctx: commands.Context, channel: discord.TextChannel
    ) -> None:
        """Set the channel where member joins via vouched invites are logged."""
        await self.config.guild(ctx.guild).member_log_channel_id.set(channel.id)
        await ctx.send(f"✅ Member join log channel set to {channel.mention}.")

    @invitevouch.command(name="targetchannel")
    async def set_target_channel(
        self, ctx: commands.Context, channel: discord.TextChannel
    ) -> None:
        """Set the landing channel for generated invites (e.g. #information)."""
        await self.config.guild(ctx.guild).invite_channel_id.set(channel.id)
        await ctx.send(f"✅ Invite landing channel set to {channel.mention}.")

    @staticmethod
    def count_slots(invites: dict[str, dict[str, Any]], user_id: int) -> int:
        """Invites of a member that still count: used ones, and pending ones under 7 days old."""
        now = datetime.now(UTC)
        count = 0
        for data in invites.values():
            if data.get("inviter_id") != user_id or data.get("released"):
                continue
            if data.get("used"):
                count += 1
                continue
            try:
                age = now - datetime.fromisoformat(data["created_at"])
            except (KeyError, ValueError):
                count += 1
                continue
            if age.total_seconds() < 86400 * 7:
                count += 1
        return count

    @invitevouch.command(name="limit")
    async def set_limit(self, ctx: commands.Context, amount: int) -> None:
        """How many invites each member may create (0 = unlimited). Staff are exempt."""
        await self.config.guild(ctx.guild).max_per_member.set(max(0, amount))
        await ctx.send(
            f"✅ Members may now create **{amount if amount > 0 else 'unlimited'}** invite(s)."
        )

    @invitevouch.command(name="reset")
    async def reset_member(self, ctx: commands.Context, member: discord.Member) -> None:
        """Give a member their invite allowance back (keeps the history)."""
        freed = 0
        async with self.config.guild(ctx.guild).invites() as inv_dict:
            for data in inv_dict.values():
                if data.get("inviter_id") == member.id and not data.get("released"):
                    data["released"] = True
                    freed += 1
        await ctx.send(f"✅ Released {freed} invite(s) for {member.mention}.")

    @invitevouch.command(name="list")
    async def list_invites(self, ctx: commands.Context) -> None:
        """List all generated vouched invites."""
        invites = await self.config.guild(ctx.guild).invites()
        if not invites:
            await ctx.send("No invites recorded in database.")
            return

        lines = []
        for code, data in list(invites.items())[-20:]:
            status = "✅ used" if data.get("used") else "⏳ pending"
            lines.append(
                f"`{code}` ({status}) - by <@{data['inviter_id']}> for **{data['target_name']}**"
            )

        text = "\n".join(lines)
        if len(text) > MESSAGE_LIMIT:
            text = text[-1900:]
        await ctx.send(f"**Recent Invites:**\n{text}")

    @invitevouch.command(name="info")
    async def invite_info(self, ctx: commands.Context, code: str) -> None:
        """Get details for a specific invite code."""
        invites = await self.config.guild(ctx.guild).invites()
        data = invites.get(code)
        if not data:
            await ctx.send(f"No data found for invite `{code}`.")
            return

        embed = discord.Embed(
            title=f"Details for Invite `{code}`", color=discord.Color.blue()
        )
        embed.add_field(
            name="Inviter",
            value=f"<@{data['inviter_id']}> ({data['inviter_id']})",
            inline=True,
        )
        embed.add_field(name="Vouched For", value=data["target_name"], inline=True)
        embed.add_field(
            name="Status", value="Used" if data.get("used") else "Pending", inline=True
        )
        embed.add_field(name="Reason", value=f"```{data['reason']}```", inline=False)
        embed.add_field(
            name="Created At", value=data.get("created_at", "unknown"), inline=True
        )
        if data.get("joined_user_id"):
            embed.add_field(
                name="Joined User", value=f"<@{data['joined_user_id']}>", inline=True
            )
        await ctx.send(embed=embed)
