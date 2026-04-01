## 🏗️ Modern Hybrid Architecture
- **Hybrid Command Suite**: All `stream` and `stream set` commands are implemented using `@commands.hybrid_group` and `@commands.hybrid_command`.
- **Autocomplete & Choices**:
    - **Platform**: Fully autocompletes `tiktok`, `twitch`, `youtube`.
    - **Feature**: Uses native Discord choices for `voice` and `chat`.
- **Bulk Update (No Global Flags)**: `[p]stream set toggle <platform> <voice|chat> <state>` iterates through all individual monitors and updates their flags. This ensures granular control without sacrificing the ease of global management.

## 📺 Platform Specifics
- **TikTok**: Event-driven client using `TikTokLive`. Supports `sessionid` for private streams via `stream set tiktok session`.
- **Twitch**: Polling-based Helix API integration. Requires `client_id` and `client_secret` via `stream set twitch`.
- **YouTube**: No-API-key scraper integration.

## 🔊 Identity Synchronization
- For all platforms, the bot can dynamically match the streamer's **nickname and avatar** when joining a voice channel.
- Identity is reverted to original server state when the voice session ends.

## 🏗️ Shared Utilities
- **StaggeredRetry**: All polling platforms (Twitch, YouTube) use an exponential backoff while streamers are offline.
- **WebhookManager**: Automatic provisioning of "Mirror" webhooks for rich bridged chat/status.
