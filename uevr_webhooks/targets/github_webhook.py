import aiohttp
import logging
from .base import BaseTarget
from ..models import UEVRProfile

log = logging.getLogger("red.blu.uevr_webhooks")

class GitHubTarget(BaseTarget):
    """Target for repository dispatch to GitHub actions."""
    
    def __init__(self, token_provider):
        self.token_provider = token_provider # Function to get current token

    def to_payload(self, profile: UEVRProfile) -> dict:
        """Converts profile into a GitHub repository_dispatch event payload."""
        # We can reconstruct the "hass" / generic payload here or pass it in.
        # For isolation, let's define it explicitly or use a helper.
        client_payload = {
            "sourceName": profile.archive.sourceName,
            "gameName": profile.title,
            "authorName": profile.archive.authorName,
            "filename": profile.archive.filename,
            "sourceDownloadUrl": profile.archive.sourceDownloadUrl,
            "sourceUrl": profile.archive.sourceUrl,
            "timestamp": profile.archive.timestamp,
            "internal_path": profile.internal_path,
            "zipHash": profile.archive.zipHash,
            "content": profile.content
        }
        return {
            "event_type": "new_uevr_profile",
            "client_payload": client_payload
        }
        
    async def send(self, profile: UEVRProfile, session: aiohttp.ClientSession, hooks: list[str]) -> None:
        token = await self.token_provider()
        if not hooks or not token:
            return
            
        github_payload = self.to_payload(profile)
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "Authorization": f"Bearer {token}"
        }
        
        for webhook_url in hooks:
            if not webhook_url: continue
            try:
                async with session.post(webhook_url, headers=headers, json=github_payload) as resp:
                    if resp.status < 300:
                        log.info(f"[Targets] Triggered GitHub repository_dispatch: {webhook_url}")
                    elif resp.status >= 400:
                        log.warning(f"[Targets] GitHub webhook returned error: {resp.status}")
            except Exception as e:
                log.error(f"[Targets] Failed to trigger GitHub webhook: {e}")
