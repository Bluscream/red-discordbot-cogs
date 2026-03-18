from typing import List
import discord
from ..models import UEVRArchive

class DiscordSource:
    """Discord is handled purely by events, so it doesn't poll. This class just provides a parser."""
    
    source_name = "Discord"
    
    @staticmethod
    def parse_message(message: discord.Message) -> List[UEVRArchive]:
        """Convert a discord message event into a list of UEVRArchives (one per zip attachment)."""
        archives = []
        valid_extensions = ('.zip', '.7z', '.rar')
        valid_attachments = [a for a in message.attachments if any(a.filename.lower().endswith(ext) for ext in valid_extensions)]
        
        if not valid_attachments:
            return archives
            
        game_name = message.channel.name if hasattr(message.channel, "name") else "Unknown Thread"
        msg_url = f"https://discord.com/channels/{message.guild.id}/{message.channel.id}/{message.id}"
        
        for att in valid_attachments:
            # We don't have zipHash yet since we haven't downloaded it, but the message ID + attachment ID is a perfect unique key.
            unique_id = f"{message.id}_{att.id}"
            archives.append(UEVRArchive(
                unique_id=unique_id,
                source=DiscordSource.source_name,
                game_name=game_name,
                filename=att.filename,
                author=str(message.author),
                download_url=att.url,
                message_url=msg_url,
                content=message.content,
                timestamp=message.created_at.timestamp()
            ))
            
        return archives
