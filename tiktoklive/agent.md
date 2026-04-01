# Agent Knowledge Base: TikTokLive Cog

This document captures critical architectural decisions, library-specific "gotchas," and localized patterns discovered during the development of the TikTokLive Discord bridge.

## 🎵 TikTokLive Library (v6.x+)

### Event & Attribute Mappings
The library underwent significant renaming in version 6. We discovered several events and attributes were deprecated or moved:
- **Viewer Count**: Use `RoomUserSeqEvent` instead of `RoomUserCountMessage`. 
- **Attribute Access**: The viewer count is stored in `event.total_user`, not `event.viewer_count`.
- **Proto Events**: Full definitions can be found in `TikTokLive/events/proto_events.py` (see the `.references` folder for a local copy).

### Lifecycle Management
- **Offline States**: Starting a client for an offline user throws `UserOfflineError`. We implemented a **Staggered Backoff** polling loop (starting at 60s, increasing by 10% each fail, capped at 1h) to wait for the user to go live.
- **Connection Logic**: Do not auto-join Voice Channels immediately on cog load. Instead, wait for the `ConnectEvent` to verify the stream is actually active.
- **Cleanup**: Always cancel the `client_task` and disconnect the client during `_stop_session` to prevent resource leaks.

## 🤖 Red-DiscordBot & Discord.py

### Universal Action Queue
To prevent Discord API 429 (Rate Limit) errors and ensure sequential processing of heavyweight actions, we use a centralized `ActionQueue` (`utils/action_queue.py`).
- **Throttling**: Voice Channel status updates (`channel.edit(status=...)`) are strictly throttled to **once every 15 seconds** per channel.
- **Webhooks**: Managed webhooks are used for the "Mirror" effect to allow custom nicknames and avatars for TikTok users without requiring Nitro.

### Identity Syncing
- The bot dynamically updates its **Guild Nickname** and **Server Avatar** to match the streamer when joining a VC.
- **Important**: These changes must be reverted (`_revert_identity`) upon stream end or session stop.

## 🏗️ Internal Cog Architecture

### [ActionQueue](file:///p:/Python/red-discordbot-cogs/tiktoklive/utils/action_queue.py)
A specialized worker that handles:
- `message`: Smart target resolution (Webhook URL vs Channel ID).
- `status`: Throttled VC status updates.
- `identity`: Guild member edits.
- `callback`: Safely executing async functions outside the main TikTok event loop.

### [StaggeredRetry](file:///p:/Python/red-discordbot-cogs/tiktoklive/utils/retry.py)
A reusable backoff utility. 
```python
retry = StaggeredRetry(start=60.0, multiplier=1.1, max_val=3600.0)
await retry.sleep() # Auto-compounds the wait time
```

### [WebhookManager](file:///p:/Python/red-discordbot-cogs/tiktoklive/utils/webhooks.py)
Handles the lifecycle of "TikTok Mirror" webhooks.
- `ensure_webhook()`: Deduplicates webhooks to prevent creating hundreds of identical ones.
- `delete_webhook_by_url()`: Essential for cleanup during session teardown.

> [!IMPORTANT]
> When modifying `tiktoklive.py`, always ensure that the `ActionQueue` handlers for `voice_connect` and `voice_disconnect` are correctly registered in `__init__`.
