import asyncio
import aiohttp
import logging
from .base import BaseTarget
from ..models import UEVRProfile

log = logging.getLogger("red.blu.uevr_webhooks")

class DiscordWebhookTarget(BaseTarget):
    """Target for hitting Discord Webhooks with robust rate-limit/retry logic."""
    
    def to_payload(self, profile: UEVRProfile) -> dict:
        """Converts profile into a Discord Webhook JSON payload dictionary."""
        return {"embeds": [self.to_discord_embed(profile)]}
        
    async def send(self, profile: UEVRProfile, session: aiohttp.ClientSession, hooks: list[str]) -> None:
        if not hooks:
            return
            
        json_data = self.to_payload(profile)
        
        for webhook_url in hooks:
            if not webhook_url: continue
            for _ in range(3):
                try:
                    async with session.post(webhook_url, json=json_data) as resp:
                        if resp.status == 429:
                            try:
                                data = await resp.json()
                                retry_after = data.get('retry_after', float(resp.headers.get('Retry-After', 1.0)))
                                bucket = resp.headers.get('X-RateLimit-Bucket', 'unknown')
                                log.warning(f"[Targets] Discord 429 (Rate Limit). Retry: {retry_after}s | Bucket: {bucket} | Msg: {data.get('message', 'No message')}")
                            except Exception as e:
                                retry_after = float(resp.headers.get('Retry-After', 1.0))
                                log.warning(f"[Targets] Discord 429 (Rate Limit). Retry: {retry_after}s | Error parsing JSON: {e}")
                            
                            await asyncio.sleep(retry_after + 1)
                            continue
                        elif resp.status < 300:
                            log.info(f"[Targets] Triggered Discord webhook: {webhook_url}")
                        elif resp.status >= 400:
                            log.warning(f"[Targets] Discord webhook returned error: {resp.status}")
                        break
                except Exception as e:
                    log.error(f"[Targets] Failed to trigger Discord webhook: {e}")
                    break
