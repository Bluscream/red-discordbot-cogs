"""MessageReplacer cog for Red-DiscordBot"""

import csv
import io
import shlex
from typing import List, Dict, Optional, Union
import logging

import aiohttp
import discord
from redbot.core import Config, checks, commands
from redbot.core.bot import Red

log = logging.getLogger("red.blu.messagereplacer")

class MessageReplacer(commands.Cog):
    """Deletes and reposts messages via webhooks using random profiles."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=2349872394, force_registration=True)
        
        default_guild = {
            "enabled": False,
            "replace_others": False,
            "replaced_users": [],
            "profiles": []  # List of Dict[str, str] with "name" and "avatar_url"
        }
        self.config.register_guild(**default_guild)
        self.shuffled_profiles = {}  # Dict[int, List[Dict[str, str]]]


    async def get_webhook(self, channel: discord.TextChannel) -> Optional[discord.Webhook]:
        """Get or create a webhook for the channel."""
        if not channel.permissions_for(channel.guild.me).manage_webhooks:
            return None
        try:
            webhooks = await channel.webhooks()
            for wh in webhooks:
                if wh.user == self.bot.user:
                    return wh
            return await channel.create_webhook(name="MessageReplacer Webhook")
        except discord.HTTPException:
            return None

    async def fetch_profiles_from_url(self, url: str) -> List[Dict[str, str]]:
        """Fetch and parse profiles from a CSV or TXT URL."""
        profiles = []
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
                    # First column is name, third is author image URL (if present)
                    name = row[0].strip()
                    avatar_url = row[1].strip() if len(row) > 1 else ""
                    if name:
                        profiles.append({"name": name, "avatar_url": avatar_url})
            else:
                # Text format: each line is either name, or name,avatar_url
                for line in content.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "," in line:
                        parts = [p.strip() for p in line.split(",")]
                        name = parts[0]
                        avatar_url = parts[-1] if parts[-1].startswith("http") else ""
                        profiles.append({"name": name, "avatar_url": avatar_url})
                    else:
                        profiles.append({"name": line, "avatar_url": ""})
        except Exception as e:
            log.error(f"Error fetching profiles from URL: {e}")
        return profiles

    @commands.group(invoke_without_command=True)
    @checks.admin_or_permissions(manage_messages=True)
    async def messagereplacer(self, ctx: commands.Context, *, args: str = None):
        """Configure the MessageReplacer cog or add profiles.
        
        Run without arguments to toggle the cog's enabled status.
        Provide a profile name and optional avatar URL to add a profile.
        Provide a CSV/TXT URL to load profiles from a file.
        """
        if args is None:
            # Toggle overall enabled status
            current = await self.config.guild(ctx.guild).enabled()
            await self.config.guild(ctx.guild).enabled.set(not current)
            if not current:
                await ctx.message.add_reaction("✅")
            else:
                await ctx.message.add_reaction("❌")
            return

        try:
            parsed = shlex.split(args)
        except Exception:
            parsed = args.split()

        if not parsed:
            return

        # Check if first argument is a URL
        first_arg = parsed[0]
        if first_arg.startswith(("http://", "https://")):
            # Fetch profiles from URL
            await ctx.typing()
            new_profiles = await self.fetch_profiles_from_url(first_arg)
            if new_profiles:
                await self.config.guild(ctx.guild).profiles.set(new_profiles)
                if ctx.guild.id in self.shuffled_profiles:
                    del self.shuffled_profiles[ctx.guild.id]
                await ctx.send(f"Successfully loaded and set {len(new_profiles)} profiles.")
                await ctx.message.add_reaction("✅")
            else:
                await ctx.send("Failed to load profiles from the URL. Ensure the format is correct.")
                await ctx.message.add_reaction("❌")
        else:
            # Direct profile: Name [avatarUrl]
            name = first_arg
            avatar_url = parsed[1] if len(parsed) > 1 else ""
            await self.config.guild(ctx.guild).profiles.set([{"name": name, "avatar_url": avatar_url}])
            if ctx.guild.id in self.shuffled_profiles:
                del self.shuffled_profiles[ctx.guild.id]
            await ctx.send(f"Set profile to '{name}' successfully.")
            await ctx.message.add_reaction("✅")

    @commands.command()
    async def replacemine(self, ctx: commands.Context):
        """Toggle whether your own messages are replaced."""
        user_id = ctx.author.id
        async with self.config.guild(ctx.guild).replaced_users() as replaced:
            if user_id in replaced:
                replaced.remove(user_id)
                await ctx.message.add_reaction("❌")
            else:
                replaced.append(user_id)
                await ctx.message.add_reaction("✅")

    @commands.command()
    @checks.admin_or_permissions(manage_messages=True)
    async def replaceuser(self, ctx: commands.Context, user: Union[discord.Member, discord.User]):
        """Toggle replacing messages of a specific user."""
        user_id = user.id
        async with self.config.guild(ctx.guild).replaced_users() as replaced:
            if user_id in replaced:
                replaced.remove(user_id)
                await ctx.message.add_reaction("❌")
            else:
                replaced.append(user_id)
                await ctx.message.add_reaction("✅")

    @commands.command()
    @checks.admin_or_permissions(manage_messages=True)
    async def replaceothers(self, ctx: commands.Context):
        """Toggle replacing messages of all other users."""
        current = await self.config.guild(ctx.guild).replace_others()
        await self.config.guild(ctx.guild).replace_others.set(not current)
        if not current:
            await ctx.message.add_reaction("✅")
        else:
            await ctx.message.add_reaction("❌")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Handle message deletion and webhook reposting."""
        if not message.guild or message.webhook_id:
            return

        # Skip commands to avoid breaking bot usage
        ctx = await self.bot.get_context(message)
        if ctx.valid:
            return

        guild_config = self.config.guild(message.guild)
        if not await guild_config.enabled():
            return

        # Check if the author is targeted
        author_id = message.author.id
        replaced_users = await guild_config.replaced_users()
        replace_others = await guild_config.replace_others()

        should_replace = False
        if author_id in replaced_users:
            should_replace = True
        elif replace_others and message.author != message.guild.me and not message.author.bot:
            should_replace = True

        if not should_replace:
            return

        profiles = await guild_config.profiles()
        if not profiles:
            return

        # Get channel webhook
        webhook = await self.get_webhook(message.channel)
        if not webhook:
            return

        # Pick a profile from the shuffled cache to ensure full rotation without immediate repeats
        guild_id = message.guild.id
        if guild_id not in self.shuffled_profiles or not self.shuffled_profiles[guild_id]:
            import random
            shuffled = list(profiles)
            random.shuffle(shuffled)
            self.shuffled_profiles[guild_id] = shuffled

        profile = self.shuffled_profiles[guild_id].pop()

        # Handle attachments
        files = []
        for attachment in message.attachments:
            try:
                file_bytes = await attachment.read()
                files.append(discord.File(io.BytesIO(file_bytes), filename=attachment.filename))
            except Exception:
                pass

        # Repost message
        sent = False
        try:
            await webhook.send(
                content=message.content or None,
                username=profile["name"],
                avatar_url=profile["avatar_url"] or None,
                embeds=message.embeds,
                files=files,
                allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True)
            )
            sent = True
        except Exception as e:
            log.error(f"Failed to send webhook message: {e}")

        # Delete original message only if replacement succeeded
        if sent and message.channel.permissions_for(message.guild.me).manage_messages:
            try:
                await message.delete()
            except discord.HTTPException:
                pass
