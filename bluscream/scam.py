"""Scam softban: hierarchy checks, evidence capture and the ban/purge/unban flow."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import discord
from redbot.core import modlog

if TYPE_CHECKING:
    from redbot.core.bot import Red

log = logging.getLogger("red.blu.bluscream.scam")

PURGE_SECONDS = 7 * 24 * 60 * 60
UNBAN_DELAY = 1.0
AUDIT_REASON_MAX = 512
EMBED_FIELD_MAX = 1024
MAX_EVIDENCE_FILES = 4


def clip(text: str, limit: int) -> str:
    """Shorten text to `limit` characters, marking the cut with an ellipsis."""
    return text if len(text) <= limit else text[: limit - 1] + "…"


@dataclass(frozen=True)
class Roles:
    """The positions that decide whether a softban is allowed."""

    actor_id: int
    actor_top: int
    target_id: int
    target_top: int | None  # None when the target is no longer a member
    bot_id: int
    bot_top: int
    owner_id: int
    actor_is_bot_owner: bool = False


def refusal(roles: Roles) -> str | None:
    """Return why the softban is not allowed, or None when it may go ahead."""
    if roles.target_id == roles.actor_id:
        return "You can't scam-ban yourself."
    if roles.target_id == roles.bot_id:
        return "I can't scam-ban myself."
    if roles.target_id == roles.owner_id:
        return "The server owner can't be scam-banned."
    if roles.target_top is None:
        return None
    if roles.target_top >= roles.bot_top:
        return "That member's top role is not below mine, so I can't ban them."
    exempt = roles.actor_is_bot_owner or roles.actor_id == roles.owner_id
    if not exempt and roles.target_top >= roles.actor_top:
        return "That member's top role is not below yours."
    return None


@dataclass
class Evidence:
    """What the scam message contained, captured before the purge deletes it."""

    content: str
    attachment_names: list[str]
    files: list[discord.File] = field(default_factory=list)


async def capture(message: discord.Message, size_limit: int) -> Evidence:
    """Copy the message text and up to four attachments that fit the upload limit."""
    files: list[discord.File] = []
    for attachment in message.attachments[:MAX_EVIDENCE_FILES]:
        if attachment.size > size_limit:
            continue
        try:
            files.append(await attachment.to_file(spoiler=True))
        except discord.HTTPException:
            log.warning("Could not download scam evidence %s", attachment.url)
    return Evidence(
        content=message.content,
        attachment_names=[a.filename for a in message.attachments],
        files=files,
    )


@dataclass
class Request:
    """One scam softban: who, by whom, why and where to report it."""

    guild: discord.Guild
    actor: discord.Member
    message: discord.Message
    reason: str
    report_channel: discord.TextChannel | None


def summary_embed(req: Request, evidence: Evidence) -> discord.Embed:
    """Build the report embed posted to the configured scam channel."""
    target = req.message.author
    embed = discord.Embed(color=discord.Color.red(), timestamp=discord.utils.utcnow())
    embed.set_author(name=f"Scam softban: {target}", icon_url=target.display_avatar.url)
    embed.add_field(
        name="User", value=f"{target.mention} (`{target.id}`)", inline=False
    )
    embed.add_field(
        name="Account created",
        value=discord.utils.format_dt(target.created_at, "R"),
        inline=True,
    )
    joined = target.joined_at if isinstance(target, discord.Member) else None
    embed.add_field(
        name="Joined",
        value=discord.utils.format_dt(joined, "R") if joined else "Not a member",
        inline=True,
    )
    embed.add_field(name="Channel", value=f"<#{req.message.channel.id}>", inline=True)
    embed.add_field(
        name="Reason", value=clip(req.reason, EMBED_FIELD_MAX), inline=False
    )
    embed.add_field(
        name="Message",
        value=clip(evidence.content, EMBED_FIELD_MAX)
        if evidence.content
        else "*(no text)*",
        inline=False,
    )
    if evidence.attachment_names:
        names = ", ".join(evidence.attachment_names)
        embed.add_field(
            name="Attachments", value=clip(names, EMBED_FIELD_MAX), inline=False
        )
    embed.add_field(name="Moderator", value=req.actor.mention, inline=False)
    return embed


async def softban(bot: Red, req: Request) -> str:
    """Ban with a 7-day purge, always unban again, then report. Returns a status line."""
    guild = req.guild
    target = req.message.author
    evidence = await capture(req.message, guild.filesize_limit)
    audit_reason = clip(req.reason, AUDIT_REASON_MAX)

    await guild.ban(target, reason=audit_reason, delete_message_seconds=PURGE_SECONDS)
    try:
        await asyncio.sleep(UNBAN_DELAY)
    finally:
        # The ban is only a purge tool: lift it even if the wait is cancelled.
        await guild.unban(
            target, reason=clip(f"Scam softban: {audit_reason}", AUDIT_REASON_MAX)
        )

    status = f"Scam-softbanned {target} (`{target.id}`)."
    if req.report_channel is not None:
        try:
            await req.report_channel.send(
                embed=summary_embed(req, evidence),
                files=evidence.files,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            log.exception("Could not post the scam report in %s", guild.id)
            status += " The report could not be posted."
    with contextlib.suppress(
        RuntimeError
    ):  # raised when the softban case type is disabled
        try:
            await modlog.create_case(
                bot,
                guild,
                discord.utils.utcnow(),
                "softban",
                target,
                moderator=req.actor,
                reason=audit_reason,
            )
        except discord.HTTPException:
            log.exception("Could not create the scam modlog case in %s", guild.id)
    return status


def target_problem(message: discord.Message) -> str | None:
    """Return why a message can't be scam-banned on its own grounds."""
    if message.guild is None:
        return "Scam bans only work on server messages."
    if message.webhook_id is not None:
        return "That message was sent by a webhook, not a user account."
    if message.is_system():
        return "That is a system message."
    return None
