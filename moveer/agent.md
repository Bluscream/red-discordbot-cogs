# Agent Knowledge Base: Moveer Cog

Bulk voice member migration utility.

## 🏗️ Core Features
- **Mass Migration**: Move all members from one voice channel to another in a single operation.
- **Selective Moving**: Move only members with specific roles or criteria.
- **Admin Commands**: Providing a suite of `move` commands for guild moderators.

## 🛠️ Implementation Details
- **Rate-Limiting**: Attempts to handle Discord's voice movement ratelimits by staggering requests if necessary (or using faster parallel moves when safe).
- **Guild Permissions**: Checks `Move Members` permissions for the invoking user and the bot.
- **Voice State**: Monitors active voice states to identify source and target channels.
