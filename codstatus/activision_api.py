"""Activision Status API client for Red-DiscordBot"""

from typing import Any, Dict, List, Optional, Set, Tuple
from datetime import datetime
from logging import getLogger
from pathlib import Path
import asyncio
import aiohttp
import json

log = getLogger("red.blu.activisionstatus")


class ActivisionStatus:
    """Class to interact with Activision's status API."""

    API_URL = "https://prod-psapi.infra-ext.activision.com/open/api/apexrest/oshp/landingpage"

    def __init__(self, session: Optional[aiohttp.ClientSession] = None, cache_file: Optional[Path] = None, cache_age: int = 300):
        """Initialize the ActivisionStatus class.
        
        Args:
            session: Optional aiohttp session to use
            cache_file: Optional path to cache file
            cache_age: Cache age in seconds before fetching new data (default: 300 = 5 minutes)
        """
        self.session = session
        self._last_data: Optional[Dict[str, Any]] = None
        self._last_fetch_time: Optional[datetime] = None
        self.cache_file = cache_file
        self.cache_age = cache_age

    async def fetch_status(self, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
        """Fetch the current status from Activision's API.
        
        Args:
            force_refresh: If True, bypass cache and fetch from API
        
        Returns:
            Status data dictionary or None if fetch failed
        """
        # Check cache first if not forcing refresh
        if not force_refresh:
            cached_data = self._load_cache()
            if cached_data:
                cache_time = cached_data.get("_cache_timestamp")
                if cache_time:
                    try:
                        cache_dt = datetime.fromisoformat(cache_time)
                        age = (datetime.utcnow() - cache_dt).total_seconds()
                        if age < self.cache_age:
                            log.debug(f"Using cached data (age: {age:.1f}s)")
                            self._last_data = cached_data.get("data")
                            self._last_fetch_time = cache_dt
                            return self._last_data
                        else:
                            log.debug(f"Cache expired (age: {age:.1f}s, max: {self.cache_age}s)")
                    except Exception as e:
                        log.warning(f"Error parsing cache timestamp: {e}")
        
        # Fetch from API
        if not self.session:
            async with aiohttp.ClientSession() as session:
                data = await self._fetch_with_session(session)
        else:
            data = await self._fetch_with_session(self.session)
        
        # Save to cache if fetch was successful
        if data and self.cache_file:
            self._save_cache(data)
        
        return data

    async def _fetch_with_session(self, session: aiohttp.ClientSession) -> Optional[Dict[str, Any]]:
        """Internal method to fetch status with a session."""
        try:
            async with session.get(self.API_URL, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    self._last_data = data
                    self._last_fetch_time = datetime.utcnow()
                    return data
                else:
                    log.warning(f"Failed to fetch Activision status: HTTP {response.status}")
                    return None
        except asyncio.TimeoutError:
            log.warning("Timeout while fetching Activision status")
            return None
        except aiohttp.ClientError as e:
            log.error(f"Error fetching Activision status: {e}")
            return None
        except Exception as e:
            log.error(f"Unexpected error fetching Activision status: {e}")
            return None

    def _save_cache(self, data: Dict[str, Any]) -> None:
        """Save data to cache file."""
        if not self.cache_file:
            return
        
        try:
            cache_data = {
                "_cache_timestamp": datetime.utcnow().isoformat(),
                "data": data
            }
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            with self.cache_file.open("w", encoding="utf-8") as f:
                json.dump(cache_data, f, indent=2)
            log.debug(f"Saved cache to {self.cache_file}")
        except Exception as e:
            log.warning(f"Failed to save cache: {e}")

    def _load_cache(self) -> Optional[Dict[str, Any]]:
        """Load data from cache file."""
        if not self.cache_file or not self.cache_file.exists():
            return None
        
        try:
            with self.cache_file.open("r", encoding="utf-8") as f:
                cache_data = json.load(f)
                log.debug(f"Loaded cache from {self.cache_file}")
                return cache_data
        except json.JSONDecodeError as e:
            log.warning(f"Invalid cache file format: {e}")
            return None
        except Exception as e:
            log.warning(f"Failed to load cache: {e}")
            return None

    def get_server_statuses(self, data: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Get the list of server statuses (games with issues)."""
        if data is None:
            data = self._last_data
        if not data:
            return []
        return data.get("serverStatuses", [])

    def get_platforms(self, data: Optional[Dict[str, Any]] = None) -> List[str]:
        """Get the list of available platforms."""
        if data is None:
            data = self._last_data
        if not data:
            return []
        return data.get("platformsRO", [])

    def get_red_alerts(self, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Get active red alerts."""
        if data is None:
            data = self._last_data
        if not data:
            return {}
        return data.get("redAlerts", {})

    def get_recently_resolved(self, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Get recently resolved incidents."""
        if data is None:
            data = self._last_data
        if not data:
            return {}
        return data.get("recentlyResolved", {})

    def get_updated_time(self, data: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Get the timestamp of when the data was last updated."""
        if data is None:
            data = self._last_data
        if not data:
            return None
        return data.get("updatedTime")

    def is_game_online(self, game_title: str, platform: str, data: Optional[Dict[str, Any]] = None) -> bool:
        """Check if a specific game/platform combination is online."""
        server_statuses = self.get_server_statuses(data)
        # If game/platform is NOT in serverStatuses, it's online
        has_issue = any(
            status.get("gameTitle") == game_title and status.get("platform") == platform
            for status in server_statuses
        )
        return not has_issue

    def get_games_with_issues(self, data: Optional[Dict[str, Any]] = None) -> Set[Tuple[str, str]]:
        """Get a set of (game_title, platform) tuples for games with issues."""
        server_statuses = self.get_server_statuses(data)
        return {
            (status.get("gameTitle", ""), status.get("platform", ""))
            for status in server_statuses
            if status.get("gameTitle") and status.get("platform")
        }

    def get_all_games(self, data: Optional[Dict[str, Any]] = None) -> Set[str]:
        """Get all unique game titles from server statuses."""
        server_statuses = self.get_server_statuses(data)
        return {status.get("gameTitle", "") for status in server_statuses if status.get("gameTitle")}
