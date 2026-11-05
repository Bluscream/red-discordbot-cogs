import asyncio
import logging
import re
import time
import traceback

import discord
from redbot.core import commands, Config

log = logging.getLogger("red.sticky")

DEFAULT_DELAY = 10
GITHUB_URL = "https://github.com/ToHubLab"
WEBSITE_URL = "https://finn-bot.rf.gd/"
DISCORD_URL = "http://discord.finn-bot.rf.gd"

MESSAGE_LINK_RE = re.compile(
    r"(?:https?://)?(?:canary\.|ptb\.)?discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)"
)
CUSTOM_EMOJI_RE = re.compile(r"<(a?):([^:]+):(\d+)>")

MAX_EMBEDS = 10
MAX_COMPONENT_ROWS = 5
MAX_COMPONENTS_PER_ROW = 5

CMD_BUTTON_PREFIX = "sticky_cmd"
CHECK_INTERVAL = 60
RECENT_POST_TTL = 15


# ============================================================ TRANSLATIONS ===

TRANSLATIONS = {
    "en": {
        "sticky_set": "✅ Sticky set in {channel}.",
        "sticky_updated": "✅ Sticky updated in {channel}.",
        "sticky_removed": "✅ Sticky removed from {channel}.",
        "no_sticky": "❌ No sticky in that channel.",
        "no_permission_send": "❌ I don't have permission to send messages in {channel}.",
        "message_too_long": "❌ Message is too long (max 2000 characters).",
        "invalid_link": "Invalid message link. Expected `https://discord.com/channels/<guild>/<channel>/<message>`.",
        "msg_not_found": "❌ Message not found.",
        "msg_no_access": "❌ I can't access that channel/message.",
        "msg_no_content": "❌ That message has no content, embeds or components.",
        "delay_invalid": "❌ Delay must be between 0 and 600 seconds.",
        "delay_set": "✅ Delay for {channel} set to **{seconds}s**.",
        "default_delay_set": "✅ Default delay set to **{seconds}s**.",
        "no_stickies": "No sticky messages configured.",
        "language_set": "✅ Language set to **{lang}**.",
        "debug_on": "✅ Debug mode enabled.",
        "debug_off": "✅ Debug mode disabled.",
        "settings_title": "Sticky Settings",
        "credits_title": "Sticky Cog - Credits",
        "credits_desc": "Thank you for using **Sticky**!\nThis cog is maintained by **ToHubLab**.",
        "manage_title": "Sticky in #{channel}",
        "manage_content": "Content",
        "manage_delay": "Delay",
        "manage_lastid": "Last message ID",
        "manage_extras": "Extras",
        "manage_no_sticky": "No sticky set for this channel yet. Click **Edit Text**, **Set from Message** or **Add Cmd Button**.",
        "menu_title": "Sticky Messages",
        "menu_desc": "Use the menu below to manage stickies, or click **Add New Sticky** / **Add from Message**.",
        "menu_none": "No stickies yet",
        "menu_none_value": "Click **Add New Sticky** to create your first one.",
        "default_delay_footer": "Default delay: {seconds}s - Made by ToHubLab",
        "channel_not_found": "❌ Channel not found.",
        "invalid_style": "❌ Invalid style. Use: primary, secondary, success, danger.",
        "command_button_added": "✅ Command button added (auto-delete: {auto}s).",
        "command_button_removed": "✅ Command buttons cleared.",
        "command_button_invalid": "❌ Command can't be empty.",
        "command_not_found": "❌ Command not found: `{cmd}`",
        "command_no_permission": "❌ You don't have permission to use this command.",
        "command_error": "❌ Error: {error}",
        "info_link_buttons": "ℹ️ Link buttons work permanently. Interactive buttons only show a friendly message.",
        "picked_channel_title": "Pick a channel...",
        "picked_channel_prompt": "Pick a channel for the new sticky:",
        "picked_channel_prompt_msg": "Pick a channel (from an existing message):",
        "picked_channel_prompt_cmd": "Pick a channel for the command button:",
        "lang_switched": "🌐 Language switched to **English**.",
        "settings_lang": "Language",
        "settings_debug": "Debug",
        "settings_debug_channel": "Debug channel",
        "settings_delay": "Default delay",
        "settings_count": "Stickies",
        "settings_hint": "Use the buttons below to change settings.",
        "back": "Back",
        "credits_btn": "Credits",
        "settings_btn": "Settings",
        "auto_delete_invalid": "❌ Auto-delete must be a number between 0 and 600 (0 = off).",
        "auto_delete_label": "Ephemeral delete after Xs (0 = keep)",
        "auto_delete_placeholder": "e.g. 5",
        "cmd_buttons_title": "Command Buttons — #{channel}",
        "cmd_buttons_none": "No command buttons configured for this sticky.",
        "cmd_buttons_none_short": "No command buttons",
        "cmd_buttons_hint": "Pick a button from the dropdown to remove it.",
        "cmd_buttons_placeholder": "Select a command button to remove...",
        "cmd_buttons_select_first": "❌ Please select a button first.",
        "cmd_buttons_gone": "❌ Button not found (list may have changed).",
        "cmd_button_removed_one": "✅ Removed command button `{label}`.",
        "debug_channel_set": "✅ Debug channel set to {channel}.",
        "debug_channel_cleared": "✅ Debug channel cleared.",
        "debug_pick_channel_title": "Pick a debug channel",
        "debug_pick_channel_prompt": "🐛 Debug is now **enabled**. Please pick a channel where I should post debug logs:",
        "debug_channel_saved": "✅ Debug channel set to {channel}.",
        "debug_channel_skipped": "ℹ️ No debug channel selected. You can set one later with `sticky settings debugchannel #channel`.",
        "debug_channel_btn": "Debug Channel",
        "skip": "Skip",
        "clear": "Clear",
    },
    "de": {
        "sticky_set": "✅ Sticky gesetzt in {channel}.",
        "sticky_updated": "✅ Sticky aktualisiert in {channel}.",
        "sticky_removed": "✅ Sticky entfernt aus {channel}.",
        "no_sticky": "❌ Kein Sticky in diesem Channel.",
        "no_permission_send": "❌ Ich habe keine Berechtigung, in {channel} zu senden.",
        "message_too_long": "❌ Nachricht zu lang (max. 2000 Zeichen).",
        "invalid_link": "Ungültiger Link. Erwartet: `https://discord.com/channels/<guild>/<channel>/<message>`.",
        "msg_not_found": "❌ Nachricht nicht gefunden.",
        "msg_no_access": "❌ Ich habe keinen Zugriff auf diesen Channel / diese Nachricht.",
        "msg_no_content": "❌ Diese Nachricht hat keinen Inhalt, Embeds oder Components.",
        "delay_invalid": "❌ Delay muss zwischen 0 und 600 Sekunden liegen.",
        "delay_set": "✅ Delay für {channel} auf **{seconds}s** gesetzt.",
        "default_delay_set": "✅ Standard-Delay auf **{seconds}s** gesetzt.",
        "no_stickies": "Keine Stickies konfiguriert.",
        "language_set": "✅ Sprache auf **{lang}** gesetzt.",
        "debug_on": "✅ Debug-Modus aktiviert.",
        "debug_off": "✅ Debug-Modus deaktiviert.",
        "settings_title": "Sticky-Einstellungen",
        "credits_title": "Sticky Cog - Credits",
        "credits_desc": "Danke, dass du **Sticky** nutzt!\nDieser Cog wird von **ToHubLab** gepflegt.",
        "manage_title": "Sticky in #{channel}",
        "manage_content": "Inhalt",
        "manage_delay": "Delay",
        "manage_lastid": "Letzte Nachrichten-ID",
        "manage_extras": "Extras",
        "manage_no_sticky": "Noch kein Sticky in diesem Channel. Klicke **Edit Text**, **Set from Message** oder **Add Cmd Button**.",
        "menu_title": "Sticky-Nachrichten",
        "menu_desc": "Nutze das Menü unten zum Verwalten, oder klicke **Add New Sticky** / **Add from Message**.",
        "menu_none": "Noch keine Stickies",
        "menu_none_value": "Klicke **Add New Sticky**, um den ersten anzulegen.",
        "default_delay_footer": "Standard-Delay: {seconds}s - Made by ToHubLab",
        "channel_not_found": "❌ Channel nicht gefunden.",
        "invalid_style": "❌ Ungültiger Style. Nutze: primary, secondary, success, danger.",
        "command_button_added": "✅ Command-Button hinzugefügt (Auto-Delete: {auto}s).",
        "command_button_removed": "✅ Command-Buttons entfernt.",
        "command_button_invalid": "❌ Befehl darf nicht leer sein.",
        "command_not_found": "❌ Befehl nicht gefunden: `{cmd}`",
        "command_no_permission": "❌ Du hast keine Berechtigung für diesen Befehl.",
        "command_error": "❌ Fehler: {error}",
        "info_link_buttons": "ℹ️ Link-Buttons funktionieren dauerhaft. Interaktive Buttons zeigen nur eine Info.",
        "picked_channel_title": "Channel auswählen...",
        "picked_channel_prompt": "Wähle einen Channel für das neue Sticky:",
        "picked_channel_prompt_msg": "Wähle einen Channel (aus existierender Nachricht):",
        "picked_channel_prompt_cmd": "Wähle einen Channel für den Command-Button:",
        "lang_switched": "🌐 Sprache auf **Deutsch** umgestellt.",
        "settings_lang": "Sprache",
        "settings_debug": "Debug",
        "settings_debug_channel": "Debug-Channel",
        "settings_delay": "Standard-Delay",
        "settings_count": "Stickies",
        "settings_hint": "Nutze die Buttons unten, um die Einstellungen zu ändern.",
        "back": "Zurück",
        "credits_btn": "Credits",
        "settings_btn": "Einstellungen",
        "auto_delete_invalid": "❌ Auto-Delete muss eine Zahl zwischen 0 und 600 sein (0 = aus).",
        "auto_delete_label": "Ephemeral löschen nach Xs (0 = behalten)",
        "auto_delete_placeholder": "z.B. 5",
        "cmd_buttons_title": "Command-Buttons — #{channel}",
        "cmd_buttons_none": "Keine Command-Buttons für dieses Sticky konfiguriert.",
        "cmd_buttons_none_short": "Keine Command-Buttons",
        "cmd_buttons_hint": "Wähle unten einen Button aus, um ihn zu entfernen.",
        "cmd_buttons_placeholder": "Command-Button zum Entfernen auswählen...",
        "cmd_buttons_select_first": "❌ Bitte zuerst einen Button auswählen.",
        "cmd_buttons_gone": "❌ Button nicht gefunden (Liste evtl. geändert).",
        "cmd_button_removed_one": "✅ Command-Button `{label}` entfernt.",
        "debug_channel_set": "✅ Debug-Channel auf {channel} gesetzt.",
        "debug_channel_cleared": "✅ Debug-Channel entfernt.",
        "debug_pick_channel_title": "Debug-Channel auswählen",
        "debug_pick_channel_prompt": "🐛 Debug ist jetzt **aktiviert**. Bitte wähle einen Channel, in den ich die Debug-Logs schreiben soll:",
        "debug_channel_saved": "✅ Debug-Channel auf {channel} gesetzt.",
        "debug_channel_skipped": "ℹ️ Kein Debug-Channel gewählt. Du kannst ihn später mit `sticky settings debugchannel #channel` setzen.",
        "debug_channel_btn": "Debug-Channel",
        "skip": "Überspringen",
        "clear": "Entfernen",
    },
}


def t(lang, key, **kwargs):
    lang = lang if lang in TRANSLATIONS else "en"
    text = TRANSLATIONS[lang].get(key) or TRANSLATIONS["en"].get(key, key)
    return text.format(**kwargs) if kwargs else text


# =============================================================== HELPERS ====


def render_mentions(guild, content):
    if guild is None or not content:
        return content
    try:
        for ch in guild.channels:
            content = content.replace(f"<#{ch.id}>", f"#{ch.name}")
        for role in guild.roles:
            content = content.replace(f"<@&{role.id}>", f"@{role.name}")
        for member in guild.members:
            content = content.replace(f"<@{member.id}>", f"@{member.display_name}")
            content = content.replace(f"<@!{member.id}>", f"@{member.display_name}")
    except Exception:
        pass
    return content


def parse_emoji(text):
    if not text:
        return None
    text = text.strip()
    if not text:
        return None
    m = CUSTOM_EMOJI_RE.match(text)
    if m:
        return {
            "id": str(int(m.group(3))),
            "name": m.group(2),
            "animated": m.group(1) == "a",
        }
    return text


def _parse_stored_emoji(raw):
    if not raw:
        return None
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        try:
            return discord.PartialEmoji(
                name=raw.get("name") or "_",
                id=int(raw["id"]),
                animated=bool(raw.get("animated", False)),
            )
        except Exception:
            return None
    return None


def _emoji_to_partial(stored):
    if not stored:
        return None
    if isinstance(stored, str):
        return stored
    if isinstance(stored, dict):
        return _parse_stored_emoji(stored)
    return None


STYLE_MAP = {
    "primary": 1,
    "blurple": 1,
    "secondary": 2,
    "grey": 2,
    "gray": 2,
    "success": 3,
    "green": 3,
    "danger": 4,
    "red": 4,
    "link": 5,
    "url": 5,
}


def _clean_component(raw):
    if not isinstance(raw, dict):
        return None
    ctype = raw.get("type")
    if ctype == 1:
        children = [_clean_component(c) for c in (raw.get("components") or [])]
        children = [c for c in children if c]
        if not children:
            return None
        return {"type": 1, "components": children[:MAX_COMPONENTS_PER_ROW]}
    if ctype == 2:
        out = {"type": 2, "style": int(raw.get("style", 2))}
        if raw.get("label"):
            out["label"] = str(raw["label"])[:80]
        if raw.get("emoji"):
            out["emoji"] = raw["emoji"]
        if raw.get("custom_id"):
            out["custom_id"] = str(raw["custom_id"])[:100]
        if raw.get("url"):
            out["url"] = raw["url"]
        if raw.get("disabled"):
            out["disabled"] = True
        return out
    if ctype == 3:
        opts = []
        for opt in (raw.get("options") or [])[:25]:
            if not isinstance(opt, dict):
                continue
            label = str(opt.get("label", ""))[:100]
            value = str(opt.get("value", ""))[:100]
            if not label or not value:
                continue
            o = {"label": label, "value": value}
            if opt.get("description"):
                o["description"] = str(opt["description"])[:100]
            if opt.get("emoji"):
                o["emoji"] = opt["emoji"]
            if opt.get("default"):
                o["default"] = True
            opts.append(o)
        if not opts:
            return None
        custom_id = str(raw.get("custom_id", ""))[:100]
        if not custom_id:
            return None
        out = {
            "type": 3,
            "custom_id": custom_id,
            "options": opts,
            "min_values": int(raw.get("min_values", 1)),
            "max_values": int(raw.get("max_values", 1)),
        }
        if raw.get("placeholder"):
            out["placeholder"] = str(raw["placeholder"])[:150]
        if raw.get("disabled"):
            out["disabled"] = True
        return out
    return None


def _capture_message(message):
    data = {}
    if message.content:
        data["content"] = message.content
    if message.embeds:
        data["embeds"] = [e.to_dict() for e in message.embeds]
    if message.components:
        cleaned = []
        for c in message.components:
            try:
                cd = _clean_component(c.to_dict())
            except Exception:
                cd = None
            if cd:
                cleaned.append(cd)
        if cleaned:
            data["components"] = cleaned
    return data


async def _fetch_message_from_link(bot, link, guild):
    m = MESSAGE_LINK_RE.search(link.strip())
    if not m:
        raise ValueError("invalid_link")
    channel_id = int(m.group(2))
    message_id = int(m.group(3))

    channel = guild.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except discord.HTTPException:
            raise ValueError("msg_no_access")
        if getattr(channel, "guild", None) != guild:
            raise ValueError("msg_no_access")

    try:
        return await channel.fetch_message(message_id)
    except discord.NotFound:
        raise ValueError("msg_not_found")
    except discord.Forbidden:
        raise ValueError("msg_no_access")
    except discord.HTTPException:
        raise ValueError("msg_no_access")


def _preview_text(data, guild=None, limit=100):
    parts = []
    content = data.get("content") or ""
    if guild and content:
        content = render_mentions(guild, content)
    if content:
        parts.append(content.replace("\n", " "))
    n_embeds = len(data.get("embeds") or [])
    if n_embeds:
        parts.append(f"[{n_embeds} Embed(s)]")
    n_rows = len(data.get("components") or [])
    n_cmds = len(data.get("command_buttons") or [])
    if n_rows or n_cmds:
        parts.append(f"[{n_rows} Row(s) / {n_cmds} Cmd(s)]")
    text = " ".join(parts).strip() or "(—)"
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    return text


def build_credits_embed(lang="en"):
    embed = discord.Embed(
        title=t(lang, "credits_title"),
        description=t(lang, "credits_desc"),
        color=discord.Color.teal(),
    )
    embed.add_field(
        name="Links",
        value=(
            f"[Website]({WEBSITE_URL})\n"
            f"[GitHub]({GITHUB_URL})\n"
            f"[Discord Support]({DISCORD_URL})"
        ),
        inline=False,
    )
    embed.set_footer(text="Sticky v4.8 - Made by ToHubLab")
    return embed


# ================================================== SYNTHETIC MESSAGE =======


class _SyntheticMessage:
    """A Message-lookalike with every attribute most commands touch."""

    def __init__(self, bot, author, channel, guild, content, message_id):
        self._state = bot._connection
        self.author = author
        self.channel = channel
        self.guild = guild
        self.content = content
        self.clean_content = content
        self.id = message_id
        self.created_at = discord.utils.utcnow()
        self.edited_at = None
        self.type = discord.MessageType.default
        self.attachments = []
        self.embeds = []
        self.components = []
        self.stickers = []
        self.mentions = []
        self.role_mentions = []
        self.channel_mentions = []
        self.jump_url = ""
        self.reference = None
        self.webhook_id = None
        self.application = None
        self.interaction = None
        self.flags = discord.MessageFlags()
        self.nonce = None
        self.tts = False
        self.mention_everyone = False
        self.pinned = False
        self.activity = None
        self.system_content = ""

    @property
    def permissions(self):
        try:
            return self.channel.permissions_for(self.guild.me)
        except Exception:
            return discord.Permissions.none()

    @property
    def author_permissions(self):
        try:
            return self.channel.permissions_for(self.author)
        except Exception:
            return discord.Permissions.none()

    async def add_reaction(self, *args, **kwargs):
        return None

    async def remove_reaction(self, *args, **kwargs):
        return None

    async def clear_reactions(self, *args, **kwargs):
        return None

    async def edit(self, *args, **kwargs):
        return None

    async def delete(self, *args, **kwargs):
        return None

    async def reply(self, content=None, **kwargs):
        try:
            return await self.channel.send(content, **kwargs)
        except Exception:
            return None

    async def pin(self, *args, **kwargs):
        return None

    async def unpin(self, *args, **kwargs):
        return None

    async def create_thread(self, *args, **kwargs):
        return None

    async def fetch_reference(self, *args, **kwargs):
        return None


class _EphemeralChannelProxy:
    """Wraps a channel so every .send() call routes to an ephemeral followup."""

    def __init__(self, real_channel, interaction, delete_after=None):
        self._real = real_channel
        self._interaction = interaction
        self._delete_after = delete_after

    @property
    def __class__(self):
        return self._real.__class__

    def __getattr__(self, name):
        return getattr(self._real, name)

    async def send(self, content=None, **kwargs):
        kwargs["ephemeral"] = True
        if self._delete_after and "delete_after" not in kwargs:
            kwargs["delete_after"] = self._delete_after
        try:
            return await self._interaction.followup.send(content, **kwargs)
        except Exception:
            return None

    async def send_ephemeral(self, content=None, **kwargs):
        return await self.send(content, **kwargs)


# ================================================ STICKY COMMAND BUTTONS ====


class StickyCommandButton(discord.ui.Button):
    """A real discord.ui.Button that fires its callback when clicked."""

    def __init__(self, guild_id, channel_id, index, *, label, style, emoji=None):
        try:
            btn_style = discord.ButtonStyle(int(style))
        except (ValueError, TypeError):
            btn_style = discord.ButtonStyle.secondary
        if btn_style == discord.ButtonStyle.link:
            btn_style = discord.ButtonStyle.secondary

        super().__init__(
            label=(label or "Button")[:80],
            style=btn_style,
            custom_id=f"{CMD_BUTTON_PREFIX}:{guild_id}:{channel_id}:{index}",
            emoji=emoji,
        )
        self._sticky_guild_id = guild_id
        self._sticky_channel_id = channel_id
        self._sticky_index = index

    async def callback(self, interaction: discord.Interaction):
        if interaction.response.is_done():
            return
        cog = interaction.client.get_cog("Sticky")
        if cog is None:
            return
        try:
            await cog._execute_command_from_button(
                interaction,
                self._sticky_guild_id,
                self._sticky_channel_id,
                self._sticky_index,
            )
        except Exception as e:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            except Exception:
                pass


class StickyView(discord.ui.View):
    """View holding real command buttons + any raw components from copied msgs."""

    def __init__(self, guild_id, channel_id, command_buttons=None, raw_components=None):
        super().__init__(timeout=None)
        self._raw = list(raw_components or [])

        for i, btn in enumerate((command_buttons or [])[:25]):
            emoji = _parse_stored_emoji(btn.get("emoji"))
            try:
                b = StickyCommandButton(
                    guild_id=guild_id,
                    channel_id=channel_id,
                    index=i,
                    label=btn.get("label") or "Button",
                    style=btn.get("style", 2),
                    emoji=emoji,
                )
                self.add_item(b)
            except Exception:
                continue

    def to_components(self):
        base = list(super().to_components())
        for row in self._raw:
            if len(base) >= MAX_COMPONENT_ROWS:
                break
            if isinstance(row, dict) and row.get("type") == 1:
                base.append(row)
        return base[:MAX_COMPONENT_ROWS]


def _build_send_kwargs(data, guild_id, channel_id, command_buttons=None):
    kwargs = {}
    content = data.get("content") or ""
    embeds_raw = data.get("embeds") or []
    components_raw = data.get("components") or []

    if content.strip():
        kwargs["content"] = content

    embeds = []
    for e in embeds_raw[:MAX_EMBEDS]:
        try:
            embeds.append(discord.Embed.from_dict(e))
        except Exception:
            continue
    if embeds:
        kwargs["embeds"] = embeds

    if command_buttons or components_raw:
        kwargs["view"] = StickyView(
            guild_id=guild_id,
            channel_id=channel_id,
            command_buttons=command_buttons or [],
            raw_components=components_raw,
        )

    if not kwargs:
        kwargs["content"] = "\u200b"
    return kwargs


# ================================================ BASE VIEW (auto-close) ====


class _AutoCloseView(discord.ui.View):
    """View that removes its components on timeout so expired buttons
    don't cause 'app did not respond' errors."""

    async def on_timeout(self):
        msg = getattr(self, "message", None)
        if msg is None:
            return
        try:
            await msg.edit(view=None)
        except Exception:
            pass


# ================================================================= MODALS ===


class StickyTextModal(discord.ui.Modal):
    def __init__(self, cog, guild, channel, existing=None, lang="en"):
        super().__init__(title=f"Sticky for #{channel.name}"[:45])
        self.cog = cog
        self.guild = guild
        self.channel = channel
        self.lang = lang
        self.text_input = discord.ui.TextInput(
            label="Message content",
            style=discord.TextStyle.paragraph,
            default=existing or "",
            required=True,
            max_length=2000,
        )
        self.add_item(self.text_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass

        content = self.text_input.value
        old = await self.cog._get_data(self.guild, self.channel.id)

        new_data = {}
        if old:
            for key in ("embeds", "components", "command_buttons", "delay"):
                if key in old:
                    new_data[key] = old[key]
        new_data["content"] = content

        success, err = await self.cog.apply_sticky(self.guild, self.channel, new_data)
        if success:
            await interaction.followup.send(
                t(self.lang, "sticky_set", channel=self.channel.mention), ephemeral=True
            )
        else:
            await interaction.followup.send(f"❌ {err}", ephemeral=True)


class MessageLinkModal(discord.ui.Modal):
    def __init__(self, cog, guild, channel, lang="en"):
        super().__init__(title=f"From message: #{channel.name}"[:45])
        self.cog = cog
        self.guild = guild
        self.channel = channel
        self.lang = lang
        self.link_input = discord.ui.TextInput(
            label="Message link",
            placeholder="https://discord.com/channels/.../.../...",
            required=True,
            max_length=200,
        )
        self.add_item(self.link_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            source = await _fetch_message_from_link(
                self.cog.bot, self.link_input.value, self.guild
            )
        except ValueError as e:
            await interaction.followup.send(
                f"❌ {t(self.lang, str(e))}", ephemeral=True
            )
            return

        captured = _capture_message(source)
        if not captured:
            await interaction.followup.send(
                t(self.lang, "msg_no_content"), ephemeral=True
            )
            return

        success, err = await self.cog.apply_sticky(self.guild, self.channel, captured)
        if success:
            msg = t(self.lang, "sticky_set", channel=self.channel.mention)
            await interaction.followup.send(
                f"{msg}\n{t(self.lang, 'info_link_buttons')}", ephemeral=True
            )
        else:
            await interaction.followup.send(f"❌ {err}", ephemeral=True)


class DelayModal(discord.ui.Modal):
    def __init__(self, cog, guild, channel, current=DEFAULT_DELAY, lang="en"):
        super().__init__(title=f"Delay for #{channel.name}"[:45])
        self.cog = cog
        self.guild = guild
        self.channel = channel
        self.lang = lang
        self.delay_input = discord.ui.TextInput(
            label="Delay in seconds (0-600)",
            placeholder="e.g. 5",
            default=str(current),
            required=True,
            max_length=4,
        )
        self.add_item(self.delay_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass

        try:
            seconds = int(self.delay_input.value)
            if seconds < 0 or seconds > 600:
                raise ValueError
        except ValueError:
            await interaction.followup.send(
                t(self.lang, "delay_invalid"), ephemeral=True
            )
            return

        data = await self.cog._get_data(self.guild, self.channel.id)
        if not data:
            await interaction.followup.send(t(self.lang, "no_sticky"), ephemeral=True)
            return

        data["delay"] = seconds
        await self.cog._set_data(self.guild, self.channel.id, data)
        await interaction.followup.send(
            t(self.lang, "delay_set", channel=self.channel.mention, seconds=seconds),
            ephemeral=True,
        )


class CommandButtonModal(discord.ui.Modal):
    def __init__(self, cog, guild, channel, lang="en"):
        super().__init__(title=f"Command Button: #{channel.name}"[:45])
        self.cog = cog
        self.guild = guild
        self.channel = channel
        self.lang = lang

        self.label_input = discord.ui.TextInput(
            label="Button label"[:45],
            placeholder="z.B. Spiele",
            required=True,
            max_length=80,
        )
        self.emoji_input = discord.ui.TextInput(
            label="Emoji (optional)"[:45],
            placeholder="😀 or <:name:1234567890>",
            required=False,
            max_length=100,
        )
        self.style_input = discord.ui.TextInput(
            label="Style (primary/secondary/success/danger)"[:45],
            default="secondary",
            required=True,
            max_length=20,
        )
        self.command_input = discord.ui.TextInput(
            label="Command (prefix auto-stripped)"[:45],
            placeholder="z.B. spiele   oder   .spiele   oder   role add @user Member",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=500,
        )
        self.auto_delete_input = discord.ui.TextInput(
            label=t(lang, "auto_delete_label")[:45],
            placeholder=t(lang, "auto_delete_placeholder"),
            required=False,
            default="0",
            max_length=3,
        )
        self.add_item(self.label_input)
        self.add_item(self.emoji_input)
        self.add_item(self.style_input)
        self.add_item(self.command_input)
        self.add_item(self.auto_delete_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass

        style_key = self.style_input.value.strip().lower()
        style_val = STYLE_MAP.get(style_key)
        if style_val is None or style_val == 5:
            await interaction.followup.send(
                t(self.lang, "invalid_style"), ephemeral=True
            )
            return

        command = self.command_input.value.strip()
        if not command:
            await interaction.followup.send(
                t(self.lang, "command_button_invalid"), ephemeral=True
            )
            return

        raw_auto = (self.auto_delete_input.value or "").strip()
        if not raw_auto:
            auto_delete = 0
        else:
            try:
                auto_delete = int(raw_auto)
                if auto_delete < 0 or auto_delete > 600:
                    raise ValueError
            except ValueError:
                await interaction.followup.send(
                    t(self.lang, "auto_delete_invalid"), ephemeral=True
                )
                return

        button = {
            "label": self.label_input.value.strip(),
            "style": style_val,
            "command": command,
            "auto_delete": auto_delete,
        }
        emoji = parse_emoji(self.emoji_input.value)
        if emoji:
            button["emoji"] = emoji

        data = await self.cog._get_data(self.guild, self.channel.id)
        if not data:
            data = {}
        buttons = list(data.get("command_buttons") or [])
        buttons.append(button)
        data["command_buttons"] = buttons

        success, err = await self.cog.apply_sticky(self.guild, self.channel, data)
        if success:
            await self.cog._debug_log(
                self.guild,
                f"➕ Command button added: label=`{button['label']}` "
                f"cmd=`{button['command']}` auto_delete=`{auto_delete}` "
                f"in <#{self.channel.id}>",
                "success",
            )
            await interaction.followup.send(
                t(self.lang, "command_button_added", auto=auto_delete), ephemeral=True
            )
        else:
            await self.cog._debug_log(
                self.guild, f"Failed to add command button: {err}", "error"
            )
            await interaction.followup.send(f"❌ {err}", ephemeral=True)


# ================================================================== VIEWS ===


class ChannelPickerView(discord.ui.View):
    def __init__(self, cog, guild, mode="text", lang="en"):
        super().__init__(timeout=120)
        self.cog = cog
        self.guild = guild
        self.mode = mode
        self.lang = lang
        self.channel_select = discord.ui.ChannelSelect(
            placeholder=t(lang, "picked_channel_title"),
            channel_types=[discord.ChannelType.text],
        )
        self.channel_select.callback = self.on_channel_pick
        self.add_item(self.channel_select)

    async def on_channel_pick(self, interaction: discord.Interaction):
        channel_ref = self.channel_select.values[0]
        channel = self.guild.get_channel(channel_ref.id)
        if channel is None:
            channel = await self.cog.bot.fetch_channel(channel_ref.id)

        if self.mode == "message":
            modal = MessageLinkModal(self.cog, self.guild, channel, self.lang)
        elif self.mode == "command":
            modal = CommandButtonModal(self.cog, self.guild, channel, self.lang)
        else:
            data = await self.cog._get_data(self.guild, channel.id)
            existing = data["content"] if data and data.get("content") else None
            modal = StickyTextModal(self.cog, self.guild, channel, existing, self.lang)
        await interaction.response.send_modal(modal)
        self.stop()


class CreditsView(_AutoCloseView):
    def __init__(self, parent=None, lang="en"):
        super().__init__(timeout=300)
        self.parent = parent
        self.lang = lang

    @discord.ui.button(
        label="Back", style=discord.ButtonStyle.secondary, emoji="◀️", row=0
    )
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.parent:
            embed = await self.parent.build_embed()
            await interaction.response.edit_message(embed=embed, view=self.parent)
        else:
            await interaction.response.edit_message(
                content="Closed.", embed=None, view=None
            )


class DebugChannelPickerView(_AutoCloseView):
    """Pick or clear the debug channel."""

    def __init__(self, cog, parent_settings, lang="en"):
        super().__init__(timeout=180)
        self.cog = cog
        self.parent_settings = parent_settings
        self.lang = lang

        self.select = discord.ui.ChannelSelect(
            placeholder=t(lang, "debug_pick_channel_title"),
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            row=0,
        )
        self.select.callback = self._on_pick
        self.add_item(self.select)

        clear = discord.ui.Button(
            label=t(lang, "clear"),
            style=discord.ButtonStyle.danger,
            emoji="🧹",
            row=1,
        )
        clear.callback = self._on_clear
        self.add_item(clear)

        skip = discord.ui.Button(
            label=t(lang, "skip"),
            style=discord.ButtonStyle.secondary,
            emoji="⏭️",
            row=1,
        )
        skip.callback = self._on_skip
        self.add_item(skip)

    async def _refresh_parent(self, guild):
        try:
            if (
                self.parent_settings is not None
                and self.parent_settings.message is not None
            ):
                embed = await self.parent_settings.build_embed()
                await self.parent_settings.message.edit(
                    embed=embed, view=self.parent_settings
                )
        except Exception:
            pass

    async def _on_pick(self, interaction: discord.Interaction):
        if not self.select.values:
            await interaction.response.send_message(
                "❌ No channel selected.", ephemeral=True
            )
            return
        channel_id = self.select.values[0].id
        await self.cog.config.guild(interaction.guild).debug_channel.set(channel_id)
        await self._refresh_parent(interaction.guild)
        await interaction.response.send_message(
            t(self.lang, "debug_channel_saved", channel=f"<#{channel_id}>"),
            ephemeral=True,
        )
        await self.cog._debug_log(
            interaction.guild,
            f"🐛 Debug channel configured by **{interaction.user}**.",
            "success",
        )
        self.stop()

    async def _on_clear(self, interaction: discord.Interaction):
        await self.cog.config.guild(interaction.guild).debug_channel.set(None)
        await self._refresh_parent(interaction.guild)
        await interaction.response.send_message(
            t(self.lang, "debug_channel_cleared"), ephemeral=True
        )
        self.stop()

    async def _on_skip(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            t(self.lang, "debug_channel_skipped"), ephemeral=True
        )
        self.stop()


class SettingsView(_AutoCloseView):
    """Settings view: language toggle, debug toggle, credits."""

    def __init__(self, cog, parent, lang, debug):
        super().__init__(timeout=300)
        self.cog = cog
        self.parent = parent
        self.lang = lang
        self.debug = debug
        self.message = None
        self._build()

    def _build(self):
        self.clear_items()

        lang_btn = discord.ui.Button(
            label="Deutsch" if self.lang == "en" else "English",
            style=discord.ButtonStyle.primary,
            emoji="🌐",
            row=0,
        )
        lang_btn.callback = self._toggle_language
        self.add_item(lang_btn)

        debug_btn = discord.ui.Button(
            label=f"Debug: {'ON' if self.debug else 'OFF'}",
            style=discord.ButtonStyle.success
            if self.debug
            else discord.ButtonStyle.secondary,
            emoji="🐛",
            row=0,
        )
        debug_btn.callback = self._toggle_debug
        self.add_item(debug_btn)

        if self.debug:
            ch_btn = discord.ui.Button(
                label=t(self.lang, "debug_channel_btn"),
                style=discord.ButtonStyle.secondary,
                emoji="📢",
                row=1,
            )
            ch_btn.callback = self._open_debug_channel_picker
            self.add_item(ch_btn)

        credits_btn = discord.ui.Button(
            label=t(self.lang, "credits_btn"),
            style=discord.ButtonStyle.secondary,
            emoji="🐙",
            row=1,
        )
        credits_btn.callback = self._show_credits
        self.add_item(credits_btn)

        back_btn = discord.ui.Button(
            label=t(self.lang, "back"),
            style=discord.ButtonStyle.secondary,
            emoji="◀️",
            row=2,
        )
        back_btn.callback = self._go_back
        self.add_item(back_btn)

    async def build_embed(self):
        default_delay = await self.cog.config.guild(self.parent.guild).default_delay()
        channels = await self.cog._all_data(self.parent.guild)
        debug_ch = await self.cog.config.guild(self.parent.guild).debug_channel()

        if debug_ch:
            ch = self.parent.guild.get_channel(debug_ch)
            debug_value = ch.mention if ch else "missing channel"
        else:
            debug_value = "not set"

        embed = discord.Embed(
            title=t(self.lang, "settings_title"),
            description=t(self.lang, "settings_hint"),
            color=discord.Color.teal(),
        )
        embed.add_field(
            name=t(self.lang, "settings_lang"), value=self.lang, inline=True
        )
        embed.add_field(
            name=t(self.lang, "settings_debug"),
            value="on" if self.debug else "off",
            inline=True,
        )
        embed.add_field(
            name=t(self.lang, "settings_debug_channel"), value=debug_value, inline=True
        )
        embed.add_field(
            name=t(self.lang, "settings_delay"), value=f"{default_delay}s", inline=True
        )
        embed.add_field(
            name=t(self.lang, "settings_count"), value=str(len(channels)), inline=True
        )
        embed.set_footer(text="Sticky v4.8 · sticky settings debugchannel #channel")
        return embed

    async def _toggle_language(self, interaction: discord.Interaction):
        new_lang = "de" if self.lang == "en" else "en"
        await self.cog.config.guild(interaction.guild).language.set(new_lang)
        self.lang = new_lang
        if self.parent:
            self.parent.lang = new_lang
            try:
                await self.parent.refresh_select()
            except Exception:
                pass
        self._build()
        embed = await self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)
        try:
            await interaction.followup.send(
                t(new_lang, "lang_switched"), ephemeral=True
            )
        except Exception:
            pass

    async def _toggle_debug(self, interaction: discord.Interaction):
        was_on = self.debug
        self.debug = not self.debug
        await self.cog.config.guild(interaction.guild).debug.set(self.debug)
        self._build()
        embed = await self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)
        try:
            self.message = interaction.message
        except Exception:
            pass

        try:
            key = "debug_on" if self.debug else "debug_off"
            await interaction.followup.send(t(self.lang, key), ephemeral=True)
        except Exception:
            pass

        if self.debug and not was_on:
            try:
                current_ch = await self.cog.config.guild(
                    interaction.guild
                ).debug_channel()
            except Exception:
                current_ch = None
            if not current_ch:
                picker = DebugChannelPickerView(
                    self.cog, parent_settings=self, lang=self.lang
                )
                try:
                    await interaction.followup.send(
                        t(self.lang, "debug_pick_channel_prompt"),
                        view=picker,
                        ephemeral=True,
                    )
                except Exception:
                    pass

    async def _open_debug_channel_picker(self, interaction: discord.Interaction):
        picker = DebugChannelPickerView(self.cog, parent_settings=self, lang=self.lang)
        await interaction.response.send_message(
            t(self.lang, "debug_pick_channel_prompt"),
            view=picker,
            ephemeral=True,
        )

    async def _show_credits(self, interaction: discord.Interaction):
        embed = build_credits_embed(self.lang)
        view = CreditsView(parent=self, lang=self.lang)
        view.message = interaction.message
        await interaction.response.edit_message(embed=embed, view=view)

    async def _go_back(self, interaction: discord.Interaction):
        if self.parent:
            embed = await self.parent.build_embed()
            await interaction.response.edit_message(embed=embed, view=self.parent)
        else:
            await interaction.response.edit_message(
                content="Closed.", embed=None, view=None
            )


class CommandButtonListView(_AutoCloseView):
    """List and remove individual command buttons from a channel's sticky."""

    def __init__(self, cog, guild, channel, parent=None, lang="en"):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild = guild
        self.channel = channel
        self.parent = parent
        self.lang = lang
        self.selected_index = None
        self.message = None

        self.select = discord.ui.Select(
            placeholder=t(lang, "cmd_buttons_placeholder"),
            options=[discord.SelectOption(label="Loading...", value="_loading")],
            row=0,
        )
        self.select.callback = self.on_select
        self.add_item(self.select)

    async def refresh_select(self):
        data = await self.cog._get_data(self.guild, self.channel.id)
        buttons = (data or {}).get("command_buttons") or []
        options = []
        for i, btn in enumerate(buttons):
            label = (btn.get("label") or f"Button {i + 1}")[:100]
            cmd = btn.get("command") or "?"
            ad = int(btn.get("auto_delete", 0) or 0)
            if ad > 0:
                desc = f"cmd: {cmd} · auto-del {ad}s"
            else:
                desc = f"cmd: {cmd}"
            options.append(
                discord.SelectOption(
                    label=label,
                    value=str(i),
                    description=desc[:100],
                    emoji=_emoji_to_partial(btn.get("emoji")),
                )
            )
        if not options:
            self.select.options = [
                discord.SelectOption(
                    label=t(self.lang, "cmd_buttons_none_short"), value="_none"
                )
            ]
            self.select.disabled = True
        else:
            self.select.options = options[:25]
            self.select.disabled = False

    async def build_embed(self):
        data = await self.cog._get_data(self.guild, self.channel.id)
        buttons = (data or {}).get("command_buttons") or []
        embed = discord.Embed(
            title=t(self.lang, "cmd_buttons_title", channel=self.channel.name),
            color=discord.Color.teal(),
        )
        if not buttons:
            embed.description = t(self.lang, "cmd_buttons_none")
        else:
            embed.description = t(self.lang, "cmd_buttons_hint")
            for i, btn in enumerate(buttons, start=1):
                label = btn.get("label") or f"Button {i}"
                cmd = btn.get("command") or "?"
                ad = int(btn.get("auto_delete", 0) or 0)
                value = f"`{cmd}`"
                if ad > 0:
                    value += f" · auto-delete: {ad}s"
                embed.add_field(name=f"{i}. {label}", value=value, inline=False)
        return embed

    async def on_select(self, interaction: discord.Interaction):
        if self.select.values[0] == "_none":
            await interaction.response.defer()
            return
        self.selected_index = int(self.select.values[0])
        try:
            await interaction.response.defer()
        except Exception:
            pass

    @discord.ui.button(
        label="Remove Selected",
        style=discord.ButtonStyle.danger,
        emoji="🗑️",
        row=1,
    )
    async def remove_selected(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if self.selected_index is None:
            await interaction.response.send_message(
                t(self.lang, "cmd_buttons_select_first"), ephemeral=True
            )
            return

        data = await self.cog._get_data(self.guild, self.channel.id)
        if not data:
            await interaction.response.send_message(
                t(self.lang, "no_sticky"), ephemeral=True
            )
            return

        buttons = list(data.get("command_buttons") or [])
        if self.selected_index < 0 or self.selected_index >= len(buttons):
            await interaction.response.send_message(
                t(self.lang, "cmd_buttons_gone"), ephemeral=True
            )
            self.selected_index = None
            await self.refresh_select()
            try:
                embed = await self.build_embed()
                await interaction.message.edit(embed=embed, view=self)
            except Exception:
                pass
            return

        removed = buttons.pop(self.selected_index)
        data["command_buttons"] = buttons
        await self.cog.apply_sticky(self.guild, self.channel, data)

        self.selected_index = None
        await self.refresh_select()
        embed = await self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)
        try:
            await interaction.followup.send(
                t(self.lang, "cmd_button_removed_one", label=removed.get("label", "?")),
                ephemeral=True,
            )
        except Exception:
            pass

    @discord.ui.button(
        label="Clear All",
        style=discord.ButtonStyle.danger,
        emoji="🧹",
        row=1,
    )
    async def clear_all(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        data = await self.cog._get_data(self.guild, self.channel.id)
        if not data:
            await interaction.response.send_message(
                t(self.lang, "no_sticky"), ephemeral=True
            )
            return
        data["command_buttons"] = []
        await self.cog.apply_sticky(self.guild, self.channel, data)
        self.selected_index = None
        await self.refresh_select()
        embed = await self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)
        try:
            await interaction.followup.send(
                t(self.lang, "command_button_removed"), ephemeral=True
            )
        except Exception:
            pass

    @discord.ui.button(
        label="Back",
        style=discord.ButtonStyle.secondary,
        emoji="◀️",
        row=1,
    )
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.parent:
            embed = await self.parent.build_embed()
            await interaction.response.edit_message(embed=embed, view=self.parent)
        else:
            await interaction.response.edit_message(
                content="Closed.", embed=None, view=None
            )


class StickyManageView(_AutoCloseView):
    def __init__(self, cog, guild, channel, parent=None, lang="en"):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild = guild
        self.channel = channel
        self.parent = parent
        self.lang = lang
        self.message = None

    async def build_embed(self):
        data = await self.cog._get_data(self.guild, self.channel.id)
        default_delay = await self.cog.config.guild(self.guild).default_delay()
        delay = data.get("delay", default_delay) if data else default_delay

        embed = discord.Embed(
            title=t(self.lang, "manage_title", channel=self.channel.name),
            color=discord.Color.teal(),
        )
        if data:
            preview = _preview_text(data, self.guild, limit=1000)
            embed.add_field(
                name=t(self.lang, "manage_content"), value=preview, inline=False
            )
            embed.add_field(
                name=t(self.lang, "manage_delay"), value=f"{delay}s", inline=True
            )
            embed.add_field(
                name=t(self.lang, "manage_lastid"),
                value=str(data.get("last_id", "N/A")),
                inline=True,
            )
            extras = []
            if data.get("embeds"):
                extras.append(f"{len(data['embeds'])} Embeds")
            if data.get("components"):
                n = sum(len(r.get("components") or []) for r in data["components"])
                extras.append(f"{n} Components")
            if data.get("command_buttons"):
                extras.append(f"{len(data['command_buttons'])} Cmd-Buttons")
            if extras:
                embed.add_field(
                    name=t(self.lang, "manage_extras"),
                    value=", ".join(extras),
                    inline=True,
                )
        else:
            embed.description = t(self.lang, "manage_no_sticky")
        return embed

    async def _go_back(self, interaction: discord.Interaction):
        if self.parent:
            await self.parent.refresh_select()
            parent_embed = await self.parent.build_embed()
            await interaction.response.edit_message(
                embed=parent_embed, view=self.parent
            )
        else:
            await interaction.response.edit_message(
                content="Closed.", embed=None, view=None
            )

    @discord.ui.button(
        label="Edit Text", style=discord.ButtonStyle.primary, emoji="✏️", row=0
    )
    async def edit_text(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        data = await self.cog._get_data(self.guild, self.channel.id)
        existing = data["content"] if data and data.get("content") else None
        modal = StickyTextModal(self.cog, self.guild, self.channel, existing, self.lang)
        await interaction.response.send_modal(modal)

    @discord.ui.button(
        label="Set from Message", style=discord.ButtonStyle.primary, emoji="📥", row=0
    )
    async def set_from_message(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        modal = MessageLinkModal(self.cog, self.guild, self.channel, self.lang)
        await interaction.response.send_modal(modal)

    @discord.ui.button(
        label="Add Cmd Button", style=discord.ButtonStyle.success, emoji="⚙️", row=1
    )
    async def add_cmd_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        modal = CommandButtonModal(self.cog, self.guild, self.channel, self.lang)
        await interaction.response.send_modal(modal)

    @discord.ui.button(
        label="Manage Cmd Buttons", style=discord.ButtonStyle.primary, emoji="📋", row=1
    )
    async def manage_cmd_buttons(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        view = CommandButtonListView(
            self.cog, self.guild, self.channel, parent=self, lang=self.lang
        )
        view.message = interaction.message
        await view.refresh_select()
        embed = await view.build_embed()
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(
        label="Change Delay", style=discord.ButtonStyle.primary, emoji="⏱️", row=0
    )
    async def change_delay(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        data = await self.cog._get_data(self.guild, self.channel.id)
        default_delay = await self.cog.config.guild(self.guild).default_delay()
        current = data.get("delay", default_delay) if data else default_delay
        modal = DelayModal(self.cog, self.guild, self.channel, current, self.lang)
        await interaction.response.send_modal(modal)

    @discord.ui.button(
        label="Remove", style=discord.ButtonStyle.danger, emoji="🗑️", row=0
    )
    async def remove(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = await self.cog._get_data(self.guild, self.channel.id)
        if data and data.get("last_id"):
            self.cog._mark_internal_delete(data["last_id"])
            try:
                msg = await self.channel.fetch_message(data["last_id"])
                await msg.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
        await self.cog._del_data(self.guild, self.channel.id)
        await self._go_back(interaction)

    @discord.ui.button(
        label="Back", style=discord.ButtonStyle.secondary, emoji="◀️", row=0
    )
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._go_back(interaction)


class StickyMenuView(_AutoCloseView):
    def __init__(self, cog, ctx, lang="en"):
        super().__init__(timeout=300)
        self.cog = cog
        self.ctx = ctx
        self.guild = ctx.guild
        self.lang = lang
        self.message = None

        self.select = discord.ui.Select(
            placeholder="Select a sticky...",
            options=[discord.SelectOption(label="Loading...", value="_loading")],
            row=1,
        )
        self.select.callback = self.on_select
        self.add_item(self.select)

    async def refresh_select(self):
        channels = await self.cog._all_data(self.guild)
        options = []
        for ch_id, data in channels.items():
            ch = self.guild.get_channel(int(ch_id))
            if ch is None:
                continue
            preview = _preview_text(data, self.guild, limit=90)
            options.append(
                discord.SelectOption(
                    label=f"#{ch.name}"[:100],
                    value=str(ch.id),
                    description=preview[:100],
                )
            )
        if not options:
            self.select.options = [
                discord.SelectOption(label=t(self.lang, "menu_none"), value="_none")
            ]
            self.select.disabled = True
        else:
            self.select.options = options[:25]
            self.select.disabled = False

    async def build_embed(self):
        channels = await self.cog._all_data(self.guild)
        default_delay = await self.cog.config.guild(self.guild).default_delay()

        embed = discord.Embed(
            title=t(self.lang, "menu_title"),
            description=t(self.lang, "menu_desc"),
            color=discord.Color.teal(),
        )
        if not channels:
            embed.add_field(
                name=t(self.lang, "menu_none"),
                value=t(self.lang, "menu_none_value"),
                inline=False,
            )
        else:
            for ch_id, data in channels.items():
                ch = self.guild.get_channel(int(ch_id))
                if ch is None:
                    continue
                preview = _preview_text(data, self.guild, limit=100)
                delay = data.get("delay", default_delay)
                embed.add_field(
                    name=f"#{ch.name} ({delay}s)", value=preview, inline=False
                )
        embed.set_footer(
            text=t(self.lang, "default_delay_footer", seconds=default_delay)
        )
        return embed

    async def on_select(self, interaction: discord.Interaction):
        value = self.select.values[0]
        if value == "_none":
            await interaction.response.defer()
            return
        channel_id = int(value)
        channel = self.guild.get_channel(channel_id)
        if channel is None:
            await interaction.response.send_message(
                t(self.lang, "channel_not_found"), ephemeral=True
            )
            return
        sub_view = StickyManageView(
            self.cog, self.guild, channel, parent=self, lang=self.lang
        )
        sub_view.message = interaction.message
        embed = await sub_view.build_embed()
        await interaction.response.edit_message(embed=embed, view=sub_view)

    @discord.ui.button(
        label="Add New Sticky", style=discord.ButtonStyle.success, emoji="➕", row=0
    )
    async def add_new(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        picker = ChannelPickerView(self.cog, self.guild, mode="text", lang=self.lang)
        await interaction.response.send_message(
            t(self.lang, "picked_channel_prompt"), view=picker, ephemeral=True
        )

    @discord.ui.button(
        label="Add from Message", style=discord.ButtonStyle.success, emoji="📥", row=0
    )
    async def add_from_message(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        picker = ChannelPickerView(self.cog, self.guild, mode="message", lang=self.lang)
        await interaction.response.send_message(
            t(self.lang, "picked_channel_prompt_msg"), view=picker, ephemeral=True
        )

    @discord.ui.button(
        label="Add Cmd Button", style=discord.ButtonStyle.success, emoji="⚙️", row=0
    )
    async def add_cmd_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        picker = ChannelPickerView(self.cog, self.guild, mode="command", lang=self.lang)
        await interaction.response.send_message(
            t(self.lang, "picked_channel_prompt_cmd"), view=picker, ephemeral=True
        )

    @discord.ui.button(
        label="Refresh", style=discord.ButtonStyle.secondary, emoji="🔄", row=0
    )
    async def refresh(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self.refresh_select()
        embed = await self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(
        label="Settings", style=discord.ButtonStyle.secondary, emoji="🔧", row=2
    )
    async def settings(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        debug = await self.cog.config.guild(interaction.guild).debug()
        view = SettingsView(self.cog, self, self.lang, debug)
        view.message = interaction.message
        embed = await view.build_embed()
        await interaction.response.edit_message(embed=embed, view=view)


# ==================================================================== COG ===


class Sticky(commands.Cog):
    """Sticky messages with text, embeds, components and command buttons."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=4578932145, force_registration=True
        )
        self.config.register_guild(
            channels={},
            default_delay=DEFAULT_DELAY,
            language="en",
            debug=False,
            debug_channel=None,
        )
        self._timers = {}
        self._locks = {}
        self._running_commands = set()
        self._open_menus = {}
        self._internal_deletes = {}
        self._check_task = None
        self._repost_again = {}
        self._recent_posts = {}

    async def cog_load(self):
        self._check_task = asyncio.create_task(self._sticky_check_loop())

    async def cog_unload(self):
        if self._check_task is not None:
            self._check_task.cancel()
            self._check_task = None
        for tsk in self._timers.values():
            tsk.cancel()
        self._timers.clear()
        self._open_menus.clear()
        self._internal_deletes.clear()
        self._repost_again.clear()
        self._recent_posts.clear()

    # ------------------------------ helpers ------------------------------

    async def _lang(self, guild):
        try:
            return await self.config.guild(guild).language()
        except Exception:
            return "en"

    async def _get_data(self, guild, channel_id):
        channels = await self.config.guild(guild).channels()
        return channels.get(str(channel_id))

    async def _all_data(self, guild):
        return await self.config.guild(guild).channels()

    async def _set_data(self, guild, channel_id, data):
        channels = await self.config.guild(guild).channels()
        channels[str(channel_id)] = data
        await self.config.guild(guild).channels.set(channels)

    async def _del_data(self, guild, channel_id):
        channels = await self.config.guild(guild).channels()
        channels.pop(str(channel_id), None)
        await self.config.guild(guild).channels.set(channels)

    def _get_lock(self, channel_id):
        if channel_id not in self._locks:
            self._locks[channel_id] = asyncio.Lock()
        return self._locks[channel_id]

    # ---------------------- internal delete tracking --------------------

    def _mark_internal_delete(self, message_id):
        if message_id:
            self._internal_deletes[int(message_id)] = time.monotonic()

    def _is_internal_delete(self, message_id):
        ts = self._internal_deletes.pop(int(message_id), None)
        if ts is None:
            return False
        return (time.monotonic() - ts) < 60

    # ---------------------------- debug log -----------------------------

    async def _debug_log(self, guild, message, level="info", exc_info=False):
        if guild is None:
            return
        try:
            if not await self.config.guild(guild).debug():
                return
        except Exception:
            return

        prefix_map = {
            "info": "🐛 **INFO**",
            "warn": "⚠️ **WARN**",
            "error": "❌ **ERROR**",
            "success": "✅ **OK**",
        }
        prefix = prefix_map.get(level, "🐛")

        log_line = f"[Sticky] {message}"
        if level == "error":
            log.error(log_line, exc_info=exc_info)
        elif level == "warn":
            log.warning(log_line)
        else:
            log.info(log_line)

        try:
            debug_channel_id = await self.config.guild(guild).debug_channel()
        except Exception:
            debug_channel_id = None
        if not debug_channel_id:
            return

        ch = guild.get_channel(debug_channel_id)
        if ch is None:
            return

        text = f"{prefix} {message}"
        if len(text) > 1900:
            text = text[:1897] + "..."

        try:
            asyncio.create_task(self._safe_debug_send(ch, text))
        except Exception:
            pass

    async def _safe_debug_send(self, channel, text):
        try:
            await channel.send(text)
        except Exception:
            pass

    # -------------------------- sticky apply ----------------------------

    async def apply_sticky(self, guild, channel, new_data):
        old = await self._get_data(guild, channel.id)

        if old and old.get("last_id"):
            self._mark_internal_delete(old["last_id"])
            try:
                old_msg = await channel.fetch_message(old["last_id"])
                await old_msg.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

        if old and "delay" in old and "delay" not in new_data:
            new_data["delay"] = old["delay"]

        kwargs = _build_send_kwargs(
            new_data,
            guild_id=guild.id,
            channel_id=channel.id,
            command_buttons=new_data.get("command_buttons") or [],
        )
        try:
            sent = await channel.send(**kwargs)
        except discord.Forbidden:
            await self._debug_log(
                guild,
                f"Forbidden when sending sticky in <#{channel.id}> — check permissions.",
                "error",
            )
            return False, t("en", "no_permission_send", channel=channel.mention)
        except discord.HTTPException as e:
            await self._debug_log(
                guild,
                f"HTTPException when sending sticky in <#{channel.id}>: {e}",
                "error",
                exc_info=True,
            )
            return False, f"HTTP error: {e}"

        new_data["last_id"] = sent.id
        await self._set_data(guild, channel.id, new_data)
        self._recent_posts[sent.id] = time.monotonic()
        await self._debug_log(
            guild,
            f"📌 Sticky applied in <#{channel.id}> — new id `{sent.id}`",
            "success",
        )
        return True, None

    # ---------------------- sticky repost (locked) ----------------------

    async def _post_sticky(self, guild, channel_id, only_if_missing=False):
        lock = self._get_lock(channel_id)
        async with lock:
            await self._post_sticky_locked(guild, channel_id, only_if_missing)

    async def _post_sticky_locked(self, guild, channel_id, only_if_missing=False):
        channel = guild.get_channel(channel_id)
        if channel is None:
            return

        data = await self._get_data(guild, channel_id)
        if not data:
            return

        if only_if_missing and data.get("last_id"):
            try:
                existing = await channel.fetch_message(data["last_id"])
                if existing and existing.author.id == self.bot.user.id:
                    return
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

        await self._debug_log(
            guild,
            f"📌 Reposting sticky in <#{channel_id}> "
            f"(old last_id={data.get('last_id')})",
        )

        if data.get("last_id"):
            self._mark_internal_delete(data["last_id"])
            try:
                old = await channel.fetch_message(data["last_id"])
                await old.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

        try:
            kwargs = _build_send_kwargs(
                data,
                guild_id=guild.id,
                channel_id=channel_id,
                command_buttons=data.get("command_buttons") or [],
            )
            new_msg = await channel.send(**kwargs)
        except discord.Forbidden:
            await self._debug_log(
                guild, f"Forbidden reposting sticky in <#{channel_id}>", "error"
            )
            return
        except discord.HTTPException as e:
            await self._debug_log(
                guild,
                f"HTTPException reposting sticky in <#{channel_id}>: {e}",
                "error",
                exc_info=True,
            )
            return

        data["last_id"] = new_msg.id
        await self._set_data(guild, channel_id, data)
        self._recent_posts[new_msg.id] = time.monotonic()
        await self._debug_log(guild, f"📌 Reposted — new id `{new_msg.id}`", "success")

    # ---------------------- duplicate detection -------------------------

    async def _find_sticky_duplicates(self, guild, channel, data, keep_id=None):
        dupes = []
        target_prefix = f"{CMD_BUTTON_PREFIX}:{guild.id}:{channel.id}:"
        has_buttons = bool(data.get("command_buttons"))
        content = (data.get("content") or "").strip()
        target_embed_titles = {
            (e.get("title") or "").strip()
            for e in (data.get("embeds") or [])
            if (e.get("title") or "").strip()
        }
        target_embed_descs = {
            (e.get("description") or "").strip()
            for e in (data.get("embeds") or [])
            if (e.get("description") or "").strip()
        }
        now = time.monotonic()

        try:
            async for msg in channel.history(limit=100):
                if msg.author.id != self.bot.user.id:
                    continue
                if keep_id and msg.id == keep_id:
                    continue
                posted_at = self._recent_posts.get(msg.id)
                if posted_at and (now - posted_at) < RECENT_POST_TTL:
                    continue
                match = False
                for row in msg.components or []:
                    for comp in getattr(row, "children", []) or []:
                        cid = getattr(comp, "custom_id", None)
                        if cid and cid.startswith(target_prefix):
                            match = True
                            break
                    if match:
                        break
                if not match:
                    if not has_buttons and content:
                        if msg.content.strip() == content:
                            match = True
                    if not match and (target_embed_titles or target_embed_descs) and msg.embeds:
                        for emb in msg.embeds:
                            t = (emb.title or "").strip()
                            d = (emb.description or "").strip()
                            if (target_embed_titles and t in target_embed_titles) or (
                                target_embed_descs and d in target_embed_descs
                            ):
                                match = True
                                break
                if match:
                    dupes.append(msg)
        except discord.HTTPException:
            pass

        return dupes

    # ---------------------- ensure single sticky ------------------------  # <-- GEAENDERT

    async def _repost_if_buried(self, guild, channel_id):
        """[blu fork] Repost a sticky that is no longer the newest message once the
        channel has been quiet for the full delay.

        The debounce timer only lives in memory, so a bot restart between a member's
        message and the repost left the sticky buried until the next message.
        """
        timer = self._timers.get(channel_id)
        if timer and not timer.done():
            return  # a debounce is already pending
        data = await self._get_data(guild, channel_id)
        if not data or not data.get("last_id"):
            return
        channel = guild.get_channel(channel_id)
        if channel is None or channel.last_message_id is None:
            return
        if channel.last_message_id == data["last_id"]:
            return  # sticky is already at the bottom
        delay = data.get("delay", await self.config.guild(guild).default_delay())
        newest = discord.utils.snowflake_time(channel.last_message_id)
        if (discord.utils.utcnow() - newest).total_seconds() < delay:
            return  # still active; the next check or a new message handles it
        await self._ensure_single_sticky(guild, channel_id, force_repost=True)

    async def _ensure_single_sticky(self, guild, channel_id, force_repost=False):
        """Guarantee exactly ONE sticky in the channel.

        force_repost=False: only repost if the tracked sticky is missing.
        force_repost=True:  always delete the tracked sticky and post a
                            fresh one (so the sticky moves to the bottom
                            after new user messages).
        """
        channel = guild.get_channel(channel_id)
        if channel is None:
            return
        lock = self._get_lock(channel_id)
        async with lock:
            data = await self._get_data(guild, channel_id)
            if not data:
                return

            last_id = data.get("last_id")
            tracked_ok = False
            if last_id and not force_repost:
                posted_at = self._recent_posts.get(int(last_id))
                if posted_at and (time.monotonic() - posted_at) < RECENT_POST_TTL:
                    tracked_ok = True
                else:
                    try:
                        msg = await channel.fetch_message(last_id)
                        if msg and msg.author.id == self.bot.user.id:
                            tracked_ok = True
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        tracked_ok = False

            keep_id = last_id if (tracked_ok and not force_repost) else None
            dupes = await self._find_sticky_duplicates(
                guild, channel, data, keep_id=keep_id
            )
            for dupe in dupes:
                self._mark_internal_delete(dupe.id)
                try:
                    await dupe.delete()
                    await self._debug_log(
                        guild,
                        f"🧹 Removed duplicate sticky `{dupe.id}` in <#{channel_id}>.",
                        "warn",
                    )
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass

            # When forcing, also delete the tracked one — it might be in
            # the recent-posts cache, so _find_sticky_duplicates skipped it.
            if force_repost and last_id:
                self._mark_internal_delete(last_id)
                try:
                    tracked = await channel.fetch_message(last_id)
                    await tracked.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass

            if force_repost or not tracked_ok:
                if force_repost:
                    await self._debug_log(
                        guild,
                        f"🔁 Force-reposting sticky in <#{channel_id}> "
                        f"(move to bottom).",
                        "warn",
                    )
                else:
                    await self._debug_log(
                        guild,
                        f"🔁 Sticky missing in <#{channel_id}> — reposting.",
                        "warn",
                    )
                data["last_id"] = None
                await self._set_data(guild, channel_id, data)
                await self._post_sticky_locked(guild, channel_id, only_if_missing=False)

    # ---------------------- periodic check loop -------------------------

    async def _sticky_check_loop(self):
        await self.bot.wait_until_ready()
        while True:
            try:
                await asyncio.sleep(CHECK_INTERVAL)

                # Prune stale recent-post markers
                now = time.monotonic()
                for mid in [m for m, ts in self._recent_posts.items() if now - ts > 60]:
                    self._recent_posts.pop(mid, None)

                for guild in list(self.bot.guilds):
                    try:
                        channels = await self._all_data(guild)
                    except Exception:
                        continue
                    for ch_id in list(channels.keys()):
                        try:
                            await self._ensure_single_sticky(guild, int(ch_id))
                            await self._repost_if_buried(guild, int(ch_id))
                        except asyncio.CancelledError:
                            raise
                        except Exception as e:
                            log.warning(
                                f"[Sticky] periodic check failed for "
                                f"guild={guild.id} channel={ch_id}: {e}"
                            )
            except asyncio.CancelledError:
                return
            except Exception as e:
                log.error(f"[Sticky] check loop crashed: {e}", exc_info=True)
                try:
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    return

    # ---------------------- debounce worker (no cancel) -----------------

    async def _schedule_repost(self, guild, channel_id):
        """Signal that a repost is needed. Never cancels a running worker."""
        existing = self._timers.get(channel_id)
        if existing and not existing.done():
            self._repost_again[channel_id] = True
            return
        self._repost_again[channel_id] = False
        self._timers[channel_id] = asyncio.create_task(
            self._repost_worker(guild, channel_id)
        )

    async def _repost_worker(self, guild, channel_id):  # <-- GEAENDERT
        """Debounced repost worker. Never cancelled mid-post."""
        try:
            while True:
                self._repost_again[channel_id] = False
                data = await self._get_data(guild, channel_id)
                if not data:
                    return
                default_delay = await self.config.guild(guild).default_delay()
                delay = data.get("delay", default_delay)
                if delay > 0:
                    await asyncio.sleep(delay)
                if self._repost_again.get(channel_id):
                    continue  # new trigger during sleep → restart debounce
                # User message arrived → sticky must move to the bottom.
                await self._ensure_single_sticky(guild, channel_id, force_repost=True)
                return
        except asyncio.CancelledError:
            raise
        finally:
            self._timers.pop(channel_id, None)
            self._repost_again.pop(channel_id, None)

    # ------------------------- command execution ------------------------

    async def _resolve_prefixes(self, guild, message=None):
        prefixes = []
        try:
            got = await self.bot.get_valid_prefixes(guild)
            if isinstance(got, str):
                got = [got]
            prefixes = list(got or [])
        except Exception:
            pass
        if not prefixes:
            try:
                got = await self.bot.get_prefix(message) if message else None
                if isinstance(got, str):
                    got = [got]
                prefixes = list(got or [])
            except Exception:
                pass
        if not prefixes:
            prefixes = ["!"]
        return prefixes

    def _strip_prefix(self, command_text, prefixes):
        for p in sorted(prefixes, key=len, reverse=True):
            if p and command_text.startswith(p):
                return command_text[len(p) :].lstrip()
        return command_text

    async def _execute_command_from_button(
        self,
        interaction: discord.Interaction,
        guild_id: int,
        channel_id: int,
        index: int,
    ):
        key = (
            interaction.user.id,
            interaction.message.id if interaction.message else 0,
        )
        if key in self._running_commands:
            return
        self._running_commands.add(key)

        try:
            try:
                await interaction.response.defer(ephemeral=True)
            except Exception:
                return

            lang = await self._lang(interaction.guild)
            debug = await self.config.guild(interaction.guild).debug()
            guild = interaction.guild

            await self._debug_log(
                guild,
                f"Button clicked by **{interaction.user}** (`{interaction.user.id}`) "
                f"in <#{channel_id}> — guild=`{guild_id}` channel=`{channel_id}` index=`{index}`",
            )

            data = await self._get_data(guild, channel_id)
            if not data:
                await self._debug_log(
                    guild, "Abort: no sticky data for this channel.", "warn"
                )
                await interaction.followup.send(t(lang, "no_sticky"), ephemeral=True)
                return
            buttons = data.get("command_buttons") or []
            if index < 0 or index >= len(buttons):
                await self._debug_log(
                    guild,
                    f"Abort: index {index} out of range (only {len(buttons)} buttons).",
                    "warn",
                )
                await interaction.followup.send(
                    t(lang, "command_not_found", cmd="?"), ephemeral=True
                )
                return

            button = buttons[index]
            raw_command = (button.get("command") or "").strip()
            await self._debug_log(
                guild,
                f"Resolved button: label=`{button.get('label', '?')}` "
                f"cmd=`{raw_command}` auto_delete=`{button.get('auto_delete', 0)}`",
            )

            if not raw_command:
                await self._debug_log(guild, "Abort: command is empty.", "warn")
                await interaction.followup.send(
                    t(lang, "command_button_invalid"), ephemeral=True
                )
                return

            auto_delete = int(button.get("auto_delete", 0) or 0)

            prefixes = await self._resolve_prefixes(guild, interaction.message)
            command_text = self._strip_prefix(raw_command, prefixes)
            await self._debug_log(
                guild,
                f"Prefixes detected: `{prefixes}` — stripped command: `{command_text}`",
            )

            prefix = None
            for p in prefixes:
                if p and not (p.startswith("<") and p.endswith(">")):
                    prefix = p
                    break
            if prefix is None:
                prefix = prefixes[0] if prefixes else "!"

            full_command = f"{prefix}{command_text}"
            await self._debug_log(guild, f"Full command to invoke: `{full_command}`")

            proxy = _EphemeralChannelProxy(
                real_channel=interaction.channel,
                interaction=interaction,
                delete_after=auto_delete if auto_delete > 0 else None,
            )

            fake_msg = _SyntheticMessage(
                bot=self.bot,
                author=interaction.user,
                channel=proxy,
                guild=guild,
                content=full_command,
                message_id=interaction.id,
            )

            ctx = await self.bot.get_context(fake_msg)

            async def _ephemeral_send(content=None, **kwargs):
                kwargs["ephemeral"] = True
                if auto_delete > 0 and "delete_after" not in kwargs:
                    kwargs["delete_after"] = auto_delete
                try:
                    return await interaction.followup.send(content, **kwargs)
                except Exception:
                    return None

            try:
                ctx.send = _ephemeral_send
                ctx.reply = _ephemeral_send
            except Exception:
                pass

            if ctx.command is None:
                await self._debug_log(
                    guild,
                    f"Command NOT found: `{full_command}` — check name/aliases. "
                    f"Available prefix(es): {prefixes}",
                    "error",
                )
                hint = ""
                if debug:
                    hint = f"\n```prefix={prefix!r}\nfull={full_command!r}```"
                await interaction.followup.send(
                    t(lang, "command_not_found", cmd=full_command) + hint,
                    ephemeral=True,
                )
                return

            await self._debug_log(
                guild, f"Command resolved: `{ctx.command.qualified_name}`"
            )

            try:
                can_run = await ctx.command.can_run(ctx)
            except Exception as e:
                await self._debug_log(
                    guild, f"can_run raised: {e}", "error", exc_info=True
                )
                can_run = False

            if not can_run:
                await self._debug_log(
                    guild,
                    f"User {interaction.user} has NO permission for "
                    f"`{ctx.command.qualified_name}`.",
                    "warn",
                )
                await interaction.followup.send(
                    t(lang, "command_no_permission"), ephemeral=True
                )
                return

            await self._debug_log(guild, f"▶️ Invoking `{ctx.command.qualified_name}` …")

            try:
                await self.bot.invoke(ctx)
                await self._debug_log(
                    guild,
                    f"✅ Executed `{ctx.command.qualified_name}` successfully.",
                    "success",
                )
            except Exception as e:
                tb = traceback.format_exc()
                await self._debug_log(
                    guild,
                    f"❌ Command `{ctx.command.qualified_name}` raised: "
                    f"`{type(e).__name__}: {e}`\n```py\n{tb[-1500:]}\n```",
                    "error",
                    exc_info=True,
                )
                try:
                    await interaction.followup.send(
                        t(lang, "command_error", error=str(e)), ephemeral=True
                    )
                except Exception:
                    pass
        finally:
            self._running_commands.discard(key)

    # ---------------------------- listeners -----------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        if message.type not in (
            discord.MessageType.default,
            discord.MessageType.reply,
            discord.MessageType.new_member,
            discord.MessageType.premium_guild_subscription,
            discord.MessageType.premium_guild_tier_1,
            discord.MessageType.premium_guild_tier_2,
            discord.MessageType.premium_guild_tier_3,
        ):
            return
        data = await self._get_data(message.guild, message.channel.id)
        if not data:
            return
        if message.id == data.get("last_id"):
            return
        await self._schedule_repost(message.guild, message.channel.id)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild:
            return
        if message.id in self._internal_deletes:
            self._internal_deletes.pop(message.id, None)
            return

        data = await self._get_data(message.guild, message.channel.id)
        if not data:
            return

        if message.id == data.get("last_id"):
            await self._debug_log(
                message.guild,
                f"🗑️ Sticky message in <#{message.channel.id}> was deleted — reposting.",
                "warn",
            )
            await self._ensure_single_sticky(message.guild, message.channel.id)

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages):
        if not messages:
            return
        guild = messages[0].guild
        if guild is None:
            return

        seen_channels = set()
        for m in messages:
            if m.channel.id in seen_channels:
                continue
            seen_channels.add(m.channel.id)

            data = await self._get_data(guild, m.channel.id)
            if not data:
                continue

            await self._ensure_single_sticky(guild, m.channel.id)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.response.is_done():
            return
        if interaction.type != discord.InteractionType.component:
            return
        data = interaction.data or {}
        custom_id = data.get("custom_id", "")
        if not custom_id.startswith(f"{CMD_BUTTON_PREFIX}:"):
            return
        parts = custom_id.split(":")
        if len(parts) != 4:
            return
        try:
            guild_id = int(parts[1])
            channel_id = int(parts[2])
            index = int(parts[3])
        except ValueError:
            return
        if not interaction.guild or interaction.guild.id != guild_id:
            return
        try:
            await self._execute_command_from_button(
                interaction, guild_id, channel_id, index
            )
        except Exception as e:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            except Exception:
                pass

    # ---------------------------- commands ------------------------------

    @commands.group(invoke_without_command=True)
    @commands.admin_or_permissions(manage_messages=True)
    async def sticky(self, ctx):
        """Manage sticky messages."""
        await ctx.send_help(ctx.command)

    @sticky.command(name="menu")
    @commands.admin_or_permissions(manage_messages=True)
    async def sticky_menu(self, ctx):
        """Open the interactive sticky menu."""
        lang = await self._lang(ctx.guild)

        old_id = self._open_menus.get(ctx.channel.id)
        if old_id:
            try:
                old_msg = await ctx.channel.fetch_message(old_id)
                await old_msg.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
            self._open_menus.pop(ctx.channel.id, None)

        view = StickyMenuView(self, ctx, lang=lang)
        await view.refresh_select()
        embed = await view.build_embed()
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg
        self._open_menus[ctx.channel.id] = msg.id

    @sticky.command(name="set")
    @commands.admin_or_permissions(manage_messages=True)
    async def sticky_set(self, ctx, channel: discord.TextChannel, *, message: str):
        """Set a text sticky in a channel."""
        lang = await self._lang(ctx.guild)
        if len(message) > 2000:
            await ctx.send(t(lang, "message_too_long"))
            return
        success, err = await self.apply_sticky(ctx.guild, channel, {"content": message})
        if success:
            await ctx.send(t(lang, "sticky_set", channel=channel.mention))
        else:
            await ctx.send(f"❌ {err}")

    @sticky.command(name="setfrom")
    @commands.admin_or_permissions(manage_messages=True)
    async def sticky_setfrom(
        self, ctx, channel: discord.TextChannel, *, message_link: str
    ):
        """Set a sticky by copying an existing message."""
        lang = await self._lang(ctx.guild)
        try:
            source = await _fetch_message_from_link(self.bot, message_link, ctx.guild)
        except ValueError as e:
            await ctx.send(f"❌ {t(lang, str(e))}")
            return
        captured = _capture_message(source)
        if not captured:
            await ctx.send(t(lang, "msg_no_content"))
            return
        success, err = await self.apply_sticky(ctx.guild, channel, captured)
        if success:
            await ctx.send(
                f"{t(lang, 'sticky_set', channel=channel.mention)}\n"
                f"{t(lang, 'info_link_buttons')}"
            )
        else:
            await ctx.send(f"❌ {err}")

    @sticky.command(name="edit")
    @commands.admin_or_permissions(manage_messages=True)
    async def sticky_edit(self, ctx, channel: discord.TextChannel, *, message: str):
        """Edit an existing sticky's text (keeps embeds/components)."""
        lang = await self._lang(ctx.guild)
        data = await self._get_data(ctx.guild, channel.id)
        if not data:
            await ctx.send(t(lang, "no_sticky"))
            return
        if len(message) > 2000:
            await ctx.send(t(lang, "message_too_long"))
            return
        new_data = {}
        for key in ("embeds", "components", "command_buttons", "delay"):
            if key in data:
                new_data[key] = data[key]
        new_data["content"] = message
        success, err = await self.apply_sticky(ctx.guild, channel, new_data)
        if success:
            await ctx.send(t(lang, "sticky_updated", channel=channel.mention))
        else:
            await ctx.send(f"❌ {err}")

    @sticky.command(name="editfrom")
    @commands.admin_or_permissions(manage_messages=True)
    async def sticky_editfrom(
        self, ctx, channel: discord.TextChannel, *, message_link: str
    ):
        """Replace a sticky with the content of another message."""
        lang = await self._lang(ctx.guild)
        data = await self._get_data(ctx.guild, channel.id)
        if not data:
            await ctx.send(t(lang, "no_sticky"))
            return
        try:
            source = await _fetch_message_from_link(self.bot, message_link, ctx.guild)
        except ValueError as e:
            await ctx.send(f"❌ {t(lang, str(e))}")
            return
        captured = _capture_message(source)
        if not captured:
            await ctx.send(t(lang, "msg_no_content"))
            return
        if data.get("command_buttons"):
            captured["command_buttons"] = data["command_buttons"]
        success, err = await self.apply_sticky(ctx.guild, channel, captured)
        if success:
            await ctx.send(t(lang, "sticky_updated", channel=channel.mention))
        else:
            await ctx.send(f"❌ {err}")

    @sticky.command(name="remove")
    @commands.admin_or_permissions(manage_messages=True)
    async def sticky_remove(self, ctx, channel: discord.TextChannel):
        """Remove a sticky from a channel."""
        lang = await self._lang(ctx.guild)
        data = await self._get_data(ctx.guild, channel.id)
        if not data:
            await ctx.send(t(lang, "no_sticky"))
            return
        if data.get("last_id"):
            self._mark_internal_delete(data["last_id"])
            try:
                msg = await channel.fetch_message(data["last_id"])
                await msg.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
        await self._del_data(ctx.guild, channel.id)
        await ctx.send(t(lang, "sticky_removed", channel=channel.mention))

    @sticky.command(name="check")
    @commands.admin_or_permissions(manage_messages=True)
    async def sticky_check(self, ctx):
        """Manually verify all stickies in this server (removes duplicates)."""
        lang = await self._lang(ctx.guild)
        channels = await self._all_data(ctx.guild)
        if not channels:
            await ctx.send(t(lang, "no_stickies"))
            return
        count = 0
        for ch_id in channels.keys():
            ch = ctx.guild.get_channel(int(ch_id))
            if ch is None:
                continue
            await self._ensure_single_sticky(ctx.guild, int(ch_id))
            count += 1
        await ctx.send(f"✅ Checked **{count}** sticky channel(s).")

    @sticky.command(name="delay")
    @commands.admin_or_permissions(manage_messages=True)
    async def sticky_delay(self, ctx, channel: discord.TextChannel, seconds: int):
        """Set a custom delay for one channel's sticky (0-600s)."""
        lang = await self._lang(ctx.guild)
        if not 0 <= seconds <= 600:
            await ctx.send(t(lang, "delay_invalid"))
            return
        data = await self._get_data(ctx.guild, channel.id)
        if not data:
            await ctx.send(t(lang, "no_sticky"))
            return
        data["delay"] = seconds
        await self._set_data(ctx.guild, channel.id, data)
        await ctx.send(t(lang, "delay_set", channel=channel.mention, seconds=seconds))

    @sticky.command(name="defaultdelay")
    @commands.admin_or_permissions(manage_messages=True)
    async def sticky_defaultdelay(self, ctx, seconds: int):
        """Set the default delay for stickies without a custom value (0-600s)."""
        lang = await self._lang(ctx.guild)
        if not 0 <= seconds <= 600:
            await ctx.send(t(lang, "delay_invalid"))
            return
        await self.config.guild(ctx.guild).default_delay.set(seconds)
        await ctx.send(t(lang, "default_delay_set", seconds=seconds))

    @sticky.command(name="list")
    @commands.admin_or_permissions(manage_messages=True)
    async def sticky_list(self, ctx):
        """Overview of all sticky messages."""
        lang = await self._lang(ctx.guild)
        channels = await self._all_data(ctx.guild)
        default_delay = await self.config.guild(ctx.guild).default_delay()
        if not channels:
            await ctx.send(t(lang, "no_stickies"))
            return
        embed = discord.Embed(title=t(lang, "menu_title"), color=discord.Color.teal())
        for ch_id, data in channels.items():
            ch = ctx.guild.get_channel(int(ch_id))
            if ch is None:
                continue
            preview = _preview_text(data, ctx.guild, limit=100)
            delay = data.get("delay", default_delay)
            embed.add_field(name=f"#{ch.name} ({delay}s)", value=preview, inline=False)
        embed.set_footer(text=t(lang, "default_delay_footer", seconds=default_delay))
        await ctx.send(embed=embed)

    @sticky.command(name="debug")
    @commands.admin_or_permissions(manage_messages=True)
    async def sticky_debug(self, ctx, channel: discord.TextChannel):
        """Show raw stored data for a sticky (troubleshooting)."""
        lang = await self._lang(ctx.guild)
        data = await self._get_data(ctx.guild, channel.id)
        if not data:
            await ctx.send(t(lang, "no_sticky"))
            return
        n_embeds = len(data.get("embeds") or [])
        n_rows = len(data.get("components") or [])
        n_comps = sum(
            len(r.get("components") or []) for r in (data.get("components") or [])
        )
        n_cmd = len(data.get("command_buttons") or [])

        embed = discord.Embed(
            title=f"Sticky Debug — #{channel.name}",
            color=discord.Color.orange(),
        )
        embed.add_field(
            name="Content length",
            value=str(len(data.get("content") or "")),
            inline=True,
        )
        embed.add_field(name="Embeds stored", value=str(n_embeds), inline=True)
        embed.add_field(name="Raw rows", value=str(n_rows), inline=True)
        embed.add_field(name="Raw components", value=str(n_comps), inline=True)
        embed.add_field(name="Command buttons", value=str(n_cmd), inline=True)
        embed.add_field(
            name="Last ID", value=str(data.get("last_id", "N/A")), inline=True
        )
        embed.add_field(
            name="Delay", value=str(data.get("delay", "default")), inline=True
        )

        if data.get("command_buttons"):
            try:
                summaries = []
                for b in data["command_buttons"][:5]:
                    ad = int(b.get("auto_delete", 0) or 0)
                    ad_txt = f" | auto-delete: {ad}s" if ad > 0 else ""
                    summaries.append(
                        f"• {b.get('label', '?')} → `{b.get('command', '?')}`{ad_txt}"
                    )
                embed.add_field(
                    name="Commands", value="\n".join(summaries), inline=False
                )
            except Exception:
                pass

        debug_on = await self.config.guild(ctx.guild).debug()
        debug_ch = await self.config.guild(ctx.guild).debug_channel()
        ch_txt = f"<#{debug_ch}>" if debug_ch else "not set"
        embed.set_footer(
            text=f"Debug mode: {'on' if debug_on else 'off'} · Debug channel: {ch_txt}"
        )
        await ctx.send(embed=embed)

    @sticky.command(name="credits")
    @commands.admin_or_permissions(manage_messages=True)
    async def sticky_credits(self, ctx):
        """Show the credits for this cog."""
        lang = await self._lang(ctx.guild)
        await ctx.send(embed=build_credits_embed(lang))

    # --------------------------- settings group --------------------------

    @sticky.group(name="settings", invoke_without_command=True)
    @commands.admin_or_permissions(manage_messages=True)
    async def sticky_settings(self, ctx):
        """Show or change cog settings."""
        lang = await self._lang(ctx.guild)
        current_lang = await self.config.guild(ctx.guild).language()
        debug = await self.config.guild(ctx.guild).debug()
        debug_ch = await self.config.guild(ctx.guild).debug_channel()
        default_delay = await self.config.guild(ctx.guild).default_delay()
        channels = await self._all_data(ctx.guild)

        embed = discord.Embed(
            title=t(lang, "settings_title"), color=discord.Color.teal()
        )
        embed.add_field(name=t(lang, "settings_lang"), value=current_lang, inline=True)
        embed.add_field(
            name=t(lang, "settings_debug"), value="on" if debug else "off", inline=True
        )
        embed.add_field(
            name=t(lang, "settings_debug_channel"),
            value=(f"<#{debug_ch}>" if debug_ch else "not set"),
            inline=True,
        )
        embed.add_field(
            name=t(lang, "settings_delay"), value=f"{default_delay}s", inline=True
        )
        embed.add_field(
            name=t(lang, "settings_count"), value=str(len(channels)), inline=True
        )
        embed.set_footer(
            text="sticky settings language <en|de> | sticky settings debug <on|off> | "
            "sticky settings debugchannel [#channel]"
        )
        await ctx.send(embed=embed)

    @sticky_settings.command(name="language")
    @commands.admin_or_permissions(manage_messages=True)
    async def sticky_settings_language(self, ctx, lang_code: str):
        """Set the cog language for this server (en/de)."""
        lang_code = lang_code.lower()
        if lang_code not in TRANSLATIONS:
            await ctx.send(f"❌ Available languages: {', '.join(TRANSLATIONS.keys())}")
            return
        await self.config.guild(ctx.guild).language.set(lang_code)
        await ctx.send(t(lang_code, "language_set", lang=lang_code))

    @sticky_settings.command(name="debug")
    @commands.admin_or_permissions(manage_messages=True)
    async def sticky_settings_debug(self, ctx, value: bool):
        """Enable or disable debug mode for this server."""
        lang = await self._lang(ctx.guild)
        await self.config.guild(ctx.guild).debug.set(value)
        if value:
            await ctx.send(t(lang, "debug_on"))
        else:
            await ctx.send(t(lang, "debug_off"))

    @sticky_settings.command(name="debugchannel")
    @commands.admin_or_permissions(manage_messages=True)
    async def sticky_settings_debugchannel(
        self, ctx, channel: discord.TextChannel = None
    ):
        """Set (or clear) the channel where debug logs are posted.

        Run without arguments to clear the debug channel.
        """
        lang = await self._lang(ctx.guild)
        if channel is None:
            await self.config.guild(ctx.guild).debug_channel.set(None)
            await ctx.send(t(lang, "debug_channel_cleared"))
            return
        await self.config.guild(ctx.guild).debug_channel.set(channel_id := channel.id)
        await ctx.send(t(lang, "debug_channel_set", channel=channel.mention))


async def setup(bot):
    await bot.add_cog(Sticky(bot))
