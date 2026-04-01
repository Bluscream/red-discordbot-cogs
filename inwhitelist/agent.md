# Agent Knowledge Base: InWhitelist Cog

A security-focused inviter-based whitelist system.

## 🏗️ Core Features
- **Inviter Logic**: Automatically whitelists or blocks users based on who invited them to the server.
- **Entry Prevention**: Kicks or bans users who join through non-whitelisted invites.
- **Whitelist Persistence**: Maintains a database of approved "Inviter" IDs.

## 🛠️ Implementation Details
- **Red Config**: Stores whitelist mappings and guild settings.
- **Audit Logs**: Monitors `on_member_join` events and cross-references them with the guild's invite list.
- **Admin Commands**: Allows manual whitelist adjustments and reporting of blocked entry attempts.
