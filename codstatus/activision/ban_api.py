"""Activision Ban Check API client for Red-DiscordBot"""

from typing import Any, Dict, Optional
from logging import getLogger
import asyncio
import aiohttp
import json
import base64
import urllib.parse
import re
import random
import string

log = getLogger("red.blu.activisionstatus")


class ActivisionBanChecker:
    """Class to interact with Activision's ban check API."""

    RECAPTCHA_API_URL = "https://www.google.com/recaptcha/enterprise/anchor"
    BAN_APPEAL_API_URL = "https://support.activision.com/api/bans/v2/appeal"
    RECAPTCHA_SITE_KEY = "6LdB2NUpAAAAANcdcy9YcjBOBD4rY-TIHOeolkkk"

    def __init__(self, session: Optional[aiohttp.ClientSession] = None):
        """Initialize the ActivisionBanChecker class.
        
        Args:
            session: Optional aiohttp session to use
        """
        self.session = session

    async def check_ban_status(self, account_id: str) -> Optional[Dict[str, Any]]:
        """Check ban status for an Activision account.
        
        Args:
            account_id: The Activision account ID to check
            
        Returns:
            Ban status data dictionary or None if check failed
        """
        try:
            # Step 1: Get reCAPTCHA token
            recaptcha_token = await self._get_recaptcha_token()
            if not recaptcha_token:
                log.error("Failed to obtain reCAPTCHA token")
                return None
            
            # Step 2: Check ban status with the token
            ban_data = await self._check_ban_with_token(account_id, recaptcha_token)
            return ban_data
            
        except Exception as e:
            log.error(f"Error checking ban status for account {account_id}: {e}")
            return None

    async def _get_recaptcha_token(self) -> Optional[str]:
        """Get a reCAPTCHA token from Google's enterprise reCAPTCHA."""
        if not self.session:
            async with aiohttp.ClientSession() as session:
                return await self._get_recaptcha_token_with_session(session)
        else:
            return await self._get_recaptcha_token_with_session(self.session)

    async def _get_recaptcha_token_with_session(self, session: aiohttp.ClientSession) -> Optional[str]:
        """Internal method to get reCAPTCHA token with a session."""
        try:
            # Generate random callback parameter
            cb = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
            
            # Build reCAPTCHA URL
            params = {
                'ar': '1',
                'k': self.RECAPTCHA_SITE_KEY,
                'co': base64.b64encode(b'https://support.activision.com:443').decode(),
                'hl': 'en',
                'v': 'PoyoqOPhxBO7pBk68S4YbpHZ',
                'size': 'normal',
                'sa': 'BAN_APPEAL',
                'anchor-ms': '20000',
                'execute-ms': '30000',
                'cb': cb
            }
            
            url = f"{self.RECAPTCHA_API_URL}?{urllib.parse.urlencode(params)}"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
                'Referer': 'https://support.activision.com/',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                'Accept-Language': 'en-US,en;q=0.9',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache'
            }
            
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    # The reCAPTCHA response is HTML, we need to extract the token
                    html_content = await response.text()
                    
                    # Look for the recaptcha token in the HTML
                    # This is a simplified approach - in practice, you might need to parse the HTML more carefully
                    token_match = re.search(r'"recaptcha-token":"([^"]+)"', html_content)
                    if token_match:
                        return token_match.group(1)
                    
                    # Alternative: look for the token in a different format
                    token_match = re.search(r'"token":"([^"]+)"', html_content)
                    if token_match:
                        return token_match.group(1)
                    
                    log.warning("Could not extract reCAPTCHA token from response")
                    return None
                else:
                    log.warning(f"Failed to get reCAPTCHA token: HTTP {response.status}")
                    return None
                    
        except asyncio.TimeoutError:
            log.warning("Timeout while getting reCAPTCHA token")
            return None
        except aiohttp.ClientError as e:
            log.error(f"Error getting reCAPTCHA token: {e}")
            return None
        except Exception as e:
            log.error(f"Unexpected error getting reCAPTCHA token: {e}")
            return None

    async def _check_ban_with_token(self, account_id: str, recaptcha_token: str) -> Optional[Dict[str, Any]]:
        """Check ban status using the reCAPTCHA token."""
        if not self.session:
            async with aiohttp.ClientSession() as session:
                return await self._check_ban_with_session(session, account_id, recaptcha_token)
        else:
            return await self._check_ban_with_session(self.session, account_id, recaptcha_token)

    async def _check_ban_with_session(self, session: aiohttp.ClientSession, account_id: str, recaptcha_token: str) -> Optional[Dict[str, Any]]:
        """Internal method to check ban status with a session."""
        try:
            # Build the URL for ban appeal API
            params = {
                'locale': 'en_US',
                'g-cc': recaptcha_token
            }
            
            url = f"{self.BAN_APPEAL_API_URL}?{urllib.parse.urlencode(params)}"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
                'Referer': 'https://support.activision.com/ban-appeal',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache',
                'X-Requested-With': 'XMLHttpRequest'
            }
            
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    return data
                else:
                    log.warning(f"Failed to check ban status: HTTP {response.status}")
                    return None
                    
        except asyncio.TimeoutError:
            log.warning("Timeout while checking ban status")
            return None
        except aiohttp.ClientError as e:
            log.error(f"Error checking ban status: {e}")
            return None
        except Exception as e:
            log.error(f"Unexpected error checking ban status: {e}")
            return None
