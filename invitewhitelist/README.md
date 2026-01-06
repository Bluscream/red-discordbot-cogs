# InviteWhitelist

A Red-DiscordBot cog for managing Discord invite whitelists through AutoMod rules.

## Features

- ✅ Automatically creates and manages an AutoMod rule for Discord invites
- ✅ Add/remove invites from whitelist with simple commands
- ✅ Resolves invite codes to server names for easy identification
- ✅ Caches server information locally
- ✅ Toggle invites on/off with a single command
- ✅ List all whitelisted invites with server names
- ✅ Enable/disable the AutoMod rule
- ✅ Admin-only commands for security

## Installation

```
[p]repo add red-discordbot-cogs https://github.com/Bluscream/red-discordbot-cogs
[p]cog install red-discordbot-cogs invitewhitelist
[p]load invitewhitelist
```

## Commands

### Main Commands

- `[p]invite` - List all whitelisted invites
- `[p]invite <code>` - Toggle an invite in the whitelist (add if not present, remove if present)

### Detailed Commands

- `[p]invite add <code>` - Add an invite to the whitelist
- `[p]invite remove <code>` - Remove an invite from the whitelist
- `[p]invite list` - List all whitelisted invites with server names
- `[p]invite info` - Show information about the AutoMod rule
- `[p]invite enable` - Enable the AutoMod rule
- `[p]invite disable` - Disable the AutoMod rule
- `[p]invite clear` - Clear all whitelisted invites (requires confirmation)

## Usage Examples

### Add an invite to whitelist
```
!invite add discord.gg/ABC123
!invite add https://discord.gg/ABC123
!invite add ABC123
```

### Remove an invite
```
!invite remove ABC123
```

### Toggle an invite (add if not present, remove if present)
```
!invite ABC123
```

### List all whitelisted invites
```
!invite
!invite list
```

## How It Works

1. When you add an invite, the cog checks if the AutoMod rule "Generated Discord invites" exists
2. If not, it creates the rule with:
   - Regex patterns to detect Discord invite links
   - Block message action with custom message
   - Alert action to log blocked invites
3. The invite code is added to the rule's allow list
4. The cog resolves the invite to get the server name and caches it locally
5. When listing invites, server names are displayed alongside codes

## Permissions Required

- **Bot**: `Manage Server` permission to create and edit AutoMod rules
- **User**: `Manage Server` permission or Administrator role to use commands

## AutoMod Rule Details

The cog creates a rule named "Generated Discord invites" with:

- **Trigger Type**: Keyword Filter (Regex)
- **Patterns**: Detects discord.gg and discordapp.com invite links
- **Actions**:
  - Block the message with custom message
  - Send alert to a log channel
- **Allow List**: Whitelisted invite codes (managed by this cog)

## Notes

- The cog automatically enables AutoMod when creating the first rule
- Invite codes are cached locally with their server names for faster lookups
- The rule can be manually edited in Discord's AutoMod settings if needed
- Expired or invalid invites will show as "Unknown/Expired" in the list

## Support

For issues, feature requests, or questions, please open an issue on GitHub.

## Author

- **Bluscream**

## Version

1.0.0
