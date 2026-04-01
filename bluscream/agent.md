# Agent Knowledge Base: Bluscream Cog

A general utility and moderation suite developed by Bluscream.

## 🏗️ Core Features
- **Moderation Workflow (Scam)**: Implements a sophisticated `ban -> purge -> unban` flow to rapidly clean up spam without permanently banning users if desired. It leverages Discord's message search API to identify and remove all content from the target user across headers/channels.
- **Bot Monitoring**: Includes a global `on_command` listener for comprehensive command execution logging.
- **Command Dumping**: Exports all bot commands to a CSV format via `dumpcmds` for documentation purposes.
- **Identity Maintenance**: Provides server-specific nickname and role management helpers (`role add`).

## 🛠️ Implementation Details
- **Hardcoded Targets**: Certain summary channels and guild IDs (e.g., `896433099100016750`) are configured for specialized logging.
- **Identity Synchronization**: Focus on keeping the bot's server-specific profile clean and well-named.
