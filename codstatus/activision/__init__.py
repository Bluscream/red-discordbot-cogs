"""Activision API module for Red-DiscordBot"""

from typing import Any, Dict, Optional
from logging import getLogger
from pathlib import Path
import aiohttp

from .status_api import ActivisionStatus
from .ban_api import ActivisionBanChecker

log = getLogger("red.blu.activisionstatus")


class ActivisionAPI:
    """Unified Activision API client combining status and ban checking functionality."""
    
    def __init__(self, session: Optional[aiohttp.ClientSession] = None, cache_file: Optional[Path] = None, cache_age: int = 300):
        """Initialize the unified Activision API client.
        
        Args:
            session: Optional aiohttp session to use
            cache_file: Optional path to cache file for status data
            cache_age: Cache age in seconds before fetching new data (default: 300 = 5 minutes)
        """
        self.session = session
        self.status_api = ActivisionStatus(session=session, cache_file=cache_file, cache_age=cache_age)
        self.ban_checker = ActivisionBanChecker(session=session)
        
        # Expose status API methods for backward compatibility
        self.API_URL = self.status_api.API_URL
        self._last_data = self.status_api._last_data
        self._last_fetch_time = self.status_api._last_fetch_time
        self.cache_file = self.status_api.cache_file
        self.cache_age = self.status_api.cache_age
    
    # Status API methods (delegated to status_api)
    async def fetch_status(self, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
        """Fetch the current status from Activision's API."""
        return await self.status_api.fetch_status(force_refresh)
    
    def get_server_statuses(self, data: Optional[Dict[str, Any]] = None) -> list:
        """Get the list of server statuses (games with issues)."""
        return self.status_api.get_server_statuses(data)
    
    def get_platforms(self, data: Optional[Dict[str, Any]] = None) -> list:
        """Get the list of available platforms."""
        return self.status_api.get_platforms(data)
    
    def get_red_alerts(self, data: Optional[Dict[str, Any]] = None) -> dict:
        """Get active red alerts."""
        return self.status_api.get_red_alerts(data)
    
    def get_recently_resolved(self, data: Optional[Dict[str, Any]] = None) -> dict:
        """Get recently resolved incidents."""
        return self.status_api.get_recently_resolved(data)
    
    def get_updated_time(self, data: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Get the timestamp of when the data was last updated."""
        return self.status_api.get_updated_time(data)
    
    def is_game_online(self, game_title: str, platform: str, data: Optional[Dict[str, Any]] = None) -> bool:
        """Check if a specific game/platform combination is online."""
        return self.status_api.is_game_online(game_title, platform, data)
    
    def get_games_with_issues(self, data: Optional[Dict[str, Any]] = None) -> set:
        """Get a set of (game_title, platform) tuples for games with issues."""
        return self.status_api.get_games_with_issues(data)
    
    def get_all_games(self, data: Optional[Dict[str, Any]] = None) -> set:
        """Get all unique game titles from server statuses."""
        return self.status_api.get_all_games(data)
    
    def _load_cache(self) -> Optional[Dict[str, Any]]:
        """Load data from cache file."""
        return self.status_api._load_cache()
    
    # Ban check methods (delegated to ban_checker)
    async def check_ban_status(self, account_id: str) -> Optional[Dict[str, Any]]:
        """Check ban status for an Activision account."""
        return await self.ban_checker.check_ban_status(account_id)


__all__ = [
    "ActivisionAPI",
    "ActivisionStatus", 
    "ActivisionBanChecker"
]
