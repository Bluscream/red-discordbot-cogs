import aiohttp
import json
from datetime import datetime
from typing import List
from .base import ProfilesSource
from ..models import UEVRArchive

class UEVRDeluxeSource(ProfilesSource):
    source_name = "uevrdeluxe.org"
    
    def __init__(self):
        self.api_url = "https://uevrdeluxefunc.azurewebsites.net/api/allprofiles"
        self.base_url = "https://uevrdeluxefunc.azurewebsites.net/api/profiles"
        
    async def fetch_new_archives(self, session: aiohttp.ClientSession, known_ids: set) -> List[UEVRArchive]:
        archives = []
        try:
            async with session.get(self.api_url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    for p in data:
                        raw_exe = p.get('exeName', '')
                        uid = p.get('ID', '')
                        
                        # Generate the composite unique ID equivalent
                        unique_id = f"uevrdeluxe_{uid}"
                        if unique_id in known_ids or not uid:
                            continue
                            
                        uuid_clean = uid.replace("-", "")
                        download_url = f"{self.base_url}/{raw_exe}/{uuid_clean}"
                        game_name = p.get('gameName', 'Unknown Game')
                        author = p.get('authorName', 'Unknown')
                        msg_url = f"https://uevr-profiles.com/" # Not a perfect URL but provides a stub
                        
                        try:
                            # UEVR Deluxe usually returns strings like "2024-03-12T10:00:00Z"
                            date_str = p.get('modifiedDate') or p.get('createdDate')
                            ts = datetime.fromisoformat(date_str.replace('Z', '+00:00')).timestamp() if date_str else None
                        except:
                            ts = None
                            
                        filename = f"{raw_exe}.zip"
                        
                        archives.append(UEVRArchive(
                            unique_id=unique_id,
                            sourceName=self.source_name,
                            gameName=game_name,
                            filename=filename,
                            authorName=author,
                            sourceDownloadUrl=download_url,
                            sourceUrl=msg_url,
                            timestamp=ts
                        ))
        except Exception as e:
            # log.error would be used here via the cog
            print(f"[UEVR Deluxe] Poll failed: {e}")
            
        return archives
