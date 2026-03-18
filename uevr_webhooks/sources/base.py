import abc
import aiohttp
from typing import List
from ..models import UEVRArchive

class ProfilesSource(abc.ABC):
    """Abstract base class for all UEVR profile sources (e.g., Discord, UEVR Deluxe, UEVR Profiles)"""
    
    @property
    @abc.abstractmethod
    def source_name(self) -> str:
        """The name of the source (e.g. 'uevrdeluxe.org')"""
        pass
        
    @abc.abstractmethod
    async def fetch_new_archives(self, session: aiohttp.ClientSession, known_ids: set) -> List[UEVRArchive]:
        """
        Polls the source for new archives.
        
        Args:
            session: The shared aiohttp ClientSession used for web requests.
            known_ids: A set of unique IDs that have already been processed to avoid duplicates.
            
        Returns:
            A list of newly discovered UEVRArchive objects.
        """
        pass
