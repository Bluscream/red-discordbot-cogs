# Agent Knowledge Base: Red-DiscordBot Cogs (Bluscream)

This repository contains a collection of cogs for Red-DiscordBot, focusing on live streaming bridges, moderation tools, and server automation.

## 🏗️ Core Architecture & Project Standards

### Shared Utilities (utils/)
A consistent "live bridge" architecture is shared across `tiktoklive`, `youtubelive`, and `twitchlive`:
- **ActionQueue**: Centralized worker that handles rate-limited Discord API calls (messages, webhooks, status, identity). 
- **StaggeredRetry**: Reusable backoff utility for polling offline streamers without hitting APIs too hard. 
- **WebhookManager**: Automatic provisioning and safe-deletion of Discord webhooks for "Mirroring" effects.
- **Formatting**: Standardized embed and string sanitization helpers.

### General Red Cog Patterns
- **Config persistence**: All data is stored using Red's `Config` system, ensuring it survives bot restarts.
- **Dependency Management**: Many older cogs utilize `pcx_lib.py` for shared functionality. Newer ones favor the specialized `utils/` pattern.
- **Author/Identity**: Most cogs are authored by **Bluscream** and maintain a common versioning/author metadata structure.

## 🛠️ Individual Cog Contexts

See the `agent.md` file within each cog's directory for specific implementation details:
- **[birthdays](file:///p:/Python/red-discordbot-cogs/birthdays/agent.md)**: Scheduled Events-based birthday tracker.
- **[bluscream](file:///p:/Python/red-discordbot-cogs/bluscream/agent.md)**: Developer & moderation utility suite (e.g., `scam` command).
- **[codstatus](file:///p:/Python/red-discordbot-cogs/codstatus/agent.md)**: Call of Duty status monitoring.
- **[gamechannel](file:///p:/Python/red-discordbot-cogs/gamechannel/agent.md)**: Dynamic voice channel automation.
- **[inwhitelist](file:///p:/Python/red-discordbot-cogs/inwhitelist/agent.md)**: Inviter-based whitelist management.
- **[moveer](file:///p:/Python/red-discordbot-cogs/moveer/agent.md)**: Massive member migration in voice channels.
- **[tiktoklive](file:///p:/Python/red-discordbot-cogs/tiktoklive/agent.md)**: The flagship live bridge that inspired the project-wide refactor.
- **[twitchlive](file:///p:/Python/red-discordbot-cogs/twitchlive/agent.md)**: Helix API-driven bridge.
- **[youtubelive](file:///p:/Python/red-discordbot-cogs/youtubelive/agent.md)**: Scraper-based no-API-key bridge.
- **[uevr_webhooks](file:///p:/Python/red-discordbot-cogs/uevr_webhooks/agent.md)**: Custom webhook listeners for UEVR updates.
