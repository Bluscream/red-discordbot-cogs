# Agent Knowledge Base: TwitchLive Cog

Extends the "Live Bridge" pattern to Twitch.

## 🎮 Twitch Monitoring (Helix API)
- **API Required**: Requires a `Client ID` and `Client Secret` obtained from the [Twitch Developer Console](https://dev.twitch.tv/).
- **Auth Token Lifecycle**: The cog manages its own App Access Token (`client_credentials` grant) and handles automatic token refreshing.
- **Helix API Endpoints**:
    - `GET /helix/streams`: Checks if a user is live and retrieves viewer count, title, and game metadata.
    - `GET /helix/users`: Retrieves streamer profile information (like avatar URLs) for identity synchronization.

## 🔊 Audio & Identity
- **HLS Extraction**: Uses `yt-dlp` to resolve the `.m3u8` from the streamer's channel link.
- **Identity Sync**: Dynamically updates the bot's Discord nickname and server avatar to match the Twitch streamer when joining a VC. This requires the `Manage Nicknames` and `Manage Webhooks` (if mirroring) permissions.

## 🏗️ Patterns
- **ActionQueue**: All Discord-side updates are pushed to the central queue to ensure rate-limiting compliance.
- **StaggeredRetry**: Background monitoring loop uses exponential backoff while the streamer is offline.
