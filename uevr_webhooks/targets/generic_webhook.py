import aiohttp
import logging
from .base import BaseTarget
from ..models import UEVRProfile

log = logging.getLogger("red.blu.uevr_webhooks")

class GenericWebhookTarget(BaseTarget):
    """Target for generic HTTP POST webhooks, primarily used for Home Assistant payloads."""
    
    def to_payload(self, profile: UEVRProfile) -> dict:
        """Converts profile into a generic Home Assistant JSON payload."""
        return {
            "event": "new_uevr_profile",
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
        
    async def send(self, profile: UEVRProfile, session: aiohttp.ClientSession, hooks: list[str]) -> None:
        if not hooks:
            return
            
        payload = self.to_payload(profile)
        
        for webhook_url in hooks:
            if not webhook_url: continue
            try:
                async with session.post(webhook_url, json=payload) as resp:
                    if resp.status >= 400:
                        log.warning(f"[Targets] Generic webhook returned error: {resp.status}")
            except Exception as e:
                log.error(f"[Targets] Failed to trigger generic webhook: {e}")
