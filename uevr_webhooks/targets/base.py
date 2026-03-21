from abc import ABC, abstractmethod
import aiohttp
from ..models import UEVRProfile

def format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    for unit in ['KB', 'MB', 'GB', 'TB']:
        size_bytes /= 1024.0
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
    return f"{size_bytes:.2f} PB"

import discord
from datetime import datetime

class BaseTarget(ABC):
    """Abstract base class for a webhook/dispatch target."""
    
    @staticmethod
    def to_discord_embed(profile: UEVRProfile) -> dict:
        """Returns a dict ready to be passed to discord.Embed().to_dict()"""
        embed = discord.Embed(
            title=f"New UEVR Profile: {profile.title}",
            description=f"`[{profile.archive.filename}]({profile.archive.sourceDownloadUrl})`",
            color=discord.Color.green(),
            timestamp=datetime.utcfromtimestamp(profile.archive.timestamp) if profile.archive.timestamp else datetime.utcnow()
        )
        embed.set_author(name=profile.archive.authorName)
        
        if profile.internal_path and profile.internal_path != "[Root]":
            embed.add_field(name="Path in archive", value=f"`{profile.internal_path}`", inline=False)
            
        if profile.archive.description:
            embed.add_field(name="Description", value=profile.archive.description[:1024], inline=False)
            
        if profile.archive.sourceUrl:
            embed.add_field(name="Source", value=f"[{profile.archive.sourceName}]({profile.archive.sourceUrl})", inline=True)
        else:
            embed.add_field(name="Source", value=profile.archive.sourceName, inline=True)
        
        if profile.archive.zipHash:
            embed.add_field(name="Archive MD5", value=f"`{profile.archive.zipHash}`", inline=True)
            
        if profile.content:
            file_list = []
            for path, info in profile.content.items():
                size_str = format_size(info.get('size', 0))
                file_list.append(f"{path} ({size_str})")
            
            # Embed fields have a 1024 char limit. Account for code block ticks and more line.
            files_str = ""
            omitted = 0
            for i, item in enumerate(file_list):
                addition = item + "\n"
                # reserve 35 chars for "```\n\n... X more\n```"
                if len(files_str) + len(addition) > 980:
                    omitted = len(file_list) - i
                    break
                files_str += addition
                
            if omitted > 0:
                files_str += f"... {omitted} more"
                
            embed.add_field(name="Content", value=f"```\n{files_str.strip()}\n```", inline=False)
            
        return embed.to_dict()    
    @abstractmethod
    async def send(self, profile: UEVRProfile, session: aiohttp.ClientSession, config_val) -> None:
        """Send the profile metadata to the specific target."""
        pass
