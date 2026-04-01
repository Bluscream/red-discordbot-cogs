# Agent Knowledge Base: YouTubeLive Cog

Extends the "Live Bridge" pattern to YouTube.

## 📺 YouTube Monitoring (Scraper)
- **No API Key**: Uses a lightweight scraper on `https://www.youtube.com/channel/{channel_id}/live` (or handle) to detect status.
- **Indicators**: Look for `"style":"LIVE"` or `'{"text":" watching"}'` in the HTML response.
- **Cookies**: Pass a `CONSENT` cookie in headers to bypass generic wall pages.

## 🔊 Audio Handling
- **HLS Extraction**: Uses `yt-dlp` to resolve the actual `.m3u8` stream URL from the channel's live link.
- **FFmpeg**: Uses standard Discord FFmpeg options with `-reconnect` flags for stream resilience.

## 🏗️ Patterns
- **ActionQueue**: Consistent use of the universal action queue for rate-limited Discord operations.
- **StaggeredRetry**: Polling logic uses exponential backoff when the streamer is offline.
