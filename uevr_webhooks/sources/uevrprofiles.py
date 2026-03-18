import aiohttp
from datetime import datetime
import urllib.parse
from typing import List
from .base import ProfilesSource
from ..models import UEVRArchive

class UEVRProfilesSource(ProfilesSource):
    source_name = "uevr-profiles.com"
    
    def __init__(self):
        self.api_url = "https://firestore.googleapis.com/v1/projects/uevrprofiles/databases/(default)/documents/games?pageSize=500"
        
    async def fetch_new_archives(self, session: aiohttp.ClientSession, known_ids: set) -> List[UEVRArchive]:
        archives = []
        try:
            async with session.get(self.api_url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    for doc in data.get('documents', []):
                        fields = doc.get('fields', {})
                        game_name = fields.get('gameName', {}).get('stringValue', 'Unknown Game')
                        profiles_array = fields.get('profiles', {}).get('arrayValue', {}).get('values', [])
                        
                        for p_val in profiles_array:
                            vf = p_val.get('mapValue', {}).get('fields', {})
                            profile_id = vf.get('id', {}).get('stringValue')
                            
                            if not profile_id:
                                continue
                                
                            unique_id = f"uevrprofiles_{profile_id}"
                            if unique_id in known_ids:
                                continue
                                
                            author = vf.get('author', {}).get('stringValue', 'Unknown')
                            desc = vf.get('description', {}).get('stringValue', '')
                            
                            date_str = vf.get('creationDate', {}).get('timestampValue')
                            try:
                                ts = datetime.fromisoformat(date_str.replace('Z', '+00:00')).timestamp() if date_str else None
                            except:
                                ts = None
                                
                            archive_file = f"{profile_id}.zip"
                            try:
                                links = vf.get('links', {}).get('arrayValue', {}).get('values', [])
                                for l in links:
                                    lf = l.get('mapValue', {}).get('fields', {})
                                    if lf.get('archive', {}).get('stringValue'):
                                        archive_file = lf.get('archive', {}).get('stringValue')
                                        break
                            except:
                                pass
                                
                            encoded_archive = urllib.parse.quote(f"profiles/{archive_file}", safe='')
                            download_url = f"https://firebasestorage.googleapis.com/v0/b/uevrprofiles.appspot.com/o/{encoded_archive}?alt=media"
                            msg_url = "https://uevr-profiles.com/"
                            
                            archives.append(UEVRArchive(
                                unique_id=unique_id,
                                source=self.source_name,
                                game_name=game_name,
                                filename=archive_file,
                                author=author,
                                download_url=download_url,
                                message_url=msg_url,
                                content=desc,
                                timestamp=ts
                            ))
        except Exception as e:
            print(f"[UEVR Profiles] Poll failed: {e}")
            
        return archives
