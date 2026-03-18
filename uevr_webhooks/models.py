import abc
import hashlib
import os
import tempfile
import zipfile
import shutil
import aiohttp
from typing import List, Optional
import discord
from datetime import datetime

def format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    for unit in ['KB', 'MB', 'GB', 'TB']:
        size_bytes /= 1024.0
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
    return f"{size_bytes:.2f} PB"

class UEVRProfile:
    """Represents an individual nested UEVR profile configuration."""
    
    def __init__(self, archive: 'UEVRArchive', title: str = None, internal_path: str = None):
        self.archive = archive
        self.title = title or archive.game_name
        self.internal_path = internal_path
        self.content = {}
        
    def to_discord_embed(self) -> dict:
        """Returns a dict ready to be passed to discord.Embed().to_dict()"""
        embed = discord.Embed(
            title=f"New UEVR Profile: {self.title}",
            description=f"A new profile archive was uploaded by **{self.archive.author}**:\n`{self.archive.filename}`",
            color=discord.Color.green(),
            timestamp=datetime.utcfromtimestamp(self.archive.timestamp) if self.archive.timestamp else datetime.utcnow()
        )
        
        if self.archive.message_url:
            embed.description += f"\n\n[Jump to Source]({self.archive.message_url})"
            
        if self.internal_path:
            embed.add_field(name="Internal Path", value=f"`{self.internal_path}`", inline=False)
            
        if self.archive.content:
            embed.add_field(name="Notes", value=self.archive.content[:1024], inline=False)
            
        embed.add_field(name="Source", value=self.archive.source, inline=True)
        
        if self.archive.zip_hash:
            embed.add_field(name="Archive Hash", value=f"`{self.archive.zip_hash}`", inline=True)
            
        if self.archive.download_url:
            embed.add_field(name="Download", value=f"[Direct Link]({self.archive.download_url})", inline=True)
            
        if self.content:
            file_list = []
            for path, info in self.content.items():
                size_str = format_size(info.get('size', 0))
                file_list.append(f"{path} ({size_str})")
            files_str = "\n".join(file_list)
            # Embed fields have a 1024 char limit. Account for code block ticks.
            if len(files_str) > 1000:
                files_str = files_str[:995] + "\n..."
            embed.add_field(name="Profile Contents", value=f"```\n{files_str}\n```", inline=False)
            
        return embed.to_dict()
        
    def to_hass_payload(self) -> dict:
        """Returns a dict payload for Home Assistant webhooks."""
        return {
            "event": "new_uevr_profile",
            "source": self.archive.source,
            "game": self.title,
            "author": self.archive.author,
            "filename": self.archive.filename,
            "download_url": self.archive.download_url,
            "message_url": self.archive.message_url,
            "timestamp": self.archive.timestamp,
            "internal_path": self.internal_path,
            "zip_hash": self.archive.zip_hash,
            "content": self.content
        }
        
    def to_github_payload(self) -> dict:
        """Returns a dict payload for GitHub repository_dispatch events."""
        return {
            "event_type": "new_uevr_profile",
            "client_payload": self.to_hass_payload()
        }


class UEVRArchive:
    """Represents a downloaded archive containing one or more UEVR profiles."""
    
    def __init__(self, 
                 unique_id: str, 
                 source: str, 
                 game_name: str, 
                 filename: str, 
                 author: str, 
                 download_url: str = None, 
                 message_url: str = None, 
                 content: str = None, 
                 timestamp: float = None):
                     
        self.unique_id = unique_id
        self.source = source
        self.game_name = game_name
        self.filename = filename
        self.author = author
        self.download_url = download_url
        self.message_url = message_url
        self.content = content
        self.timestamp = timestamp
        
        self.zip_hash: Optional[str] = None
        self.profiles: List[UEVRProfile] = []
        
        # By default, add a root profile representing the archive itself.
        # This will be replaced/extended during pre-processing if nested profiles are found.
        self.profiles.append(UEVRProfile(archive=self))
        
    @property
    def extension(self) -> str:
        if self.filename and '.' in self.filename:
            return '.' + self.filename.split('.')[-1].lower()
        return ""
        
    async def download_and_inspect(self, session: aiohttp.ClientSession):
        """Downloads the archive to a temp directory, hashes it, and inspects it for nested profiles."""
        if not self.download_url:
            print(f"[Models] No download URL for {self.filename}, skipping inspection.")
            return

        temp_dir = tempfile.mkdtemp()
        temp_file = os.path.join(temp_dir, self.filename)

        try:
            # 1. Download the file
            async with session.get(self.download_url) as resp:
                if resp.status != 200:
                    print(f"[Models] Failed to download {self.download_url}: HTTP {resp.status}")
                    return
                with open(temp_file, 'wb') as f:
                    while True:
                        chunk = await resp.content.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)

            # 2. Compute zipHash (MD5)
            hasher = hashlib.md5()
            with open(temp_file, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hasher.update(chunk)
            self.zip_hash = hasher.hexdigest().upper()

            # 3. Inspect contents (Only if .zip. For 7z/rar we currently fallback to single profile assumption unless external tools are added)
            if zipfile.is_zipfile(temp_file):
                with zipfile.ZipFile(temp_file, 'r') as zf:
                    import re
                    
                    profile_roots = set()
                    binding_pattern = re.compile(r"^bindings?_.*\.json$", re.IGNORECASE)
                    interaction_pattern = re.compile(r"^_interaction_profiles_.*\.json$", re.IGNORECASE)
                    
                    # Discover profile root directories based on Is-ProfileFolder logic
                    for f in zf.namelist():
                        if f.endswith('/'): continue
                        norm_f = f.replace('\\', '/')
                        filename = os.path.basename(norm_f)
                        dirname = os.path.dirname(norm_f)
                        
                        if (filename.lower() in ["config.txt", "profilemeta.json"] or 
                            binding_pattern.match(filename) or 
                            interaction_pattern.match(filename)):
                            
                            profile_roots.add(dirname if dirname else "[Root]")
                    
                    if profile_roots:
                        # Clear the default root profile
                        self.profiles = []
                        for internal_path in profile_roots:
                            sub_title = f"{self.game_name} ({internal_path})" if internal_path != "[Root]" else self.game_name
                            profile = UEVRProfile(archive=self, title=sub_title, internal_path=internal_path)
                            
                            prefix = internal_path + "/" if internal_path != "[Root]" else ""
                            for file_info in zf.infolist():
                                if file_info.is_dir(): continue
                                norm_name = file_info.filename.replace('\\', '/')
                                if internal_path == "[Root]" or norm_name.startswith(prefix):
                                    rel_name = norm_name[len(prefix):] if norm_name.startswith(prefix) else norm_name
                                    profile.content[rel_name] = {"size": file_info.file_size}
                                    
                            self.profiles.append(profile)
                    else:
                        for file_info in zf.infolist():
                            if file_info.is_dir(): continue
                            self.profiles[0].content[file_info.filename.replace('\\', '/')] = {"size": file_info.file_size}

        except Exception as e:
            print(f"[Models] Error inspecting {self.filename}: {e}")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
