# VoiceChannelLog

Server-side port of the Equicord `voiceChannelLog` user plugin. Voice activity is posted into
the voice channel's own text chat — or into a text channel with the same name in the same
category, if one exists — so everyone in the channel sees it, not only the plugin user.

## Events

| Event | Default message |
| :--- | :--- |
| `connect` | 🔊 @user connected to #channel |
| `disconnect` | 🔇 @user disconnected from #channel |
| `move` | 🔄 @user moved to #channel (posted in both the old and the new channel) |
| `mute` / `unmute` | self mute |
| `deafen` / `undeafen` | self deafen |
| `camera_on` / `camera_off` | camera |
| `stream_start` / `stream_stop` | Go Live |
| `server_mute` / `server_unmute` | mute by a moderator (only when the self-mute flag did not change too) |
| `server_deafen` / `server_undeafen` | deafen by a moderator (likewise) |

Mentions in log messages never ping anyone.

## Commands

All under `[p]vclog`, usable by server admins or members with Manage Server:

| Command | What it does |
| :--- | :--- |
| `enable` / `disable` | Turn logging on or off for the server (off by default) |
| `event <event> <true/false>` | Toggle one event |
| `template <event> [text]` | Custom message; no text restores the default |
| `author [name]` | Post through a webhook under this name; empty posts as the bot |
| `icon [url]` | Webhook avatar; `{avatar}` uses the member's avatar |
| `ignore <voice channel>` | Exclude / re-include a channel |
| `ignorebots <true/false>` | Skip bots (on by default) |
| `settings` | Show everything, including the placeholder list |

Placeholders: `{username}` `{displayname}` `{userid}` `{avatar}` `{oldChannelName}`
`{oldChannelId}` `{newChannelName}` `{newChannelId}` `{guildName}` `{guildId}` `{now}`.
`{now}` is a Discord timestamp, so each reader sees it in their own time zone.

## Differences from the plugin

- **`join`, `leave` and `default` are gone.** The plugin defined them but never emitted them;
  it only produced connect, disconnect and move.
- **"Only monitor own channel", guild whitelist and "trigger on own events"** described one
  client's view. The bot sees every channel, so they became `ignore <channel>` and `ignorebots`.
- **The author name default is the bot itself**, not "Clyde": Discord rejects webhook names
  containing "clyde".
- Bot permissions needed: View Channel and Send Messages in the voice channels, plus Manage
  Webhooks when `author` is set.
