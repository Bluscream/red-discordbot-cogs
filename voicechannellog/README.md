# VoiceChannelLog

Server-side port and expansion of the Equicord `voiceChannelLog` user plugin. Voice activity is posted into
the voice channel's own text chat — or into a dedicated text channel (e.g. `#voice-logs`), or both — with multiple
display modes, compact formatting, and zero user pings/mentions.

## Features

- **Zero-ping guarantee**: Mentions never ping, and default templates use non-mention display names.
- **Multiple display modes**:
  - `small` (*default*): Ultra-compact Discord subtext (`-# `). Fits maximum info in a single line.
  - `normal`: Standard clean markdown line.
  - `embed-small`: Minimalistic single-line embed with an event-colored side stripe.
  - `embed`: Full embed with member avatar, details, and timestamp.
- **Flexible destinations**:
  - Voice channel's own text chat (or same-named channel in the same category).
  - Dedicated central log channel (e.g. `[p]vclog channel #voice-logs`).
  - Or both simultaneously!

## Events

| Event | Default message |
| :--- | :--- |
| `connect` | 🟢 {time} **{displayname}** joined <#{newChannelId}> |
| `disconnect` | 🔴 {time} **{displayname}** left <#{oldChannelId}> |
| `move` | 🔄 {time} **{displayname}** moved <#{oldChannelId}> ➔ <#{newChannelId}> |
| `mute` / `unmute` | 🔇 / 🔊 {time} **{displayname}** muted / unmuted |
| `deafen` / `undeafen` | 🤐 / 👂 {time} **{displayname}** deafened / undeafened |
| `camera_on` / `camera_off` | 📹 / 📴 {time} **{displayname}** camera on / off |
| `stream_start` / `stream_stop` | 📺 / ⏹️ {time} **{displayname}** started / stopped streaming |
| `server_mute` / `server_unmute` | 🔇 / 🔊 {time} **{displayname}** was server-muted / server-unmuted |
| `server_deafen` / `server_undeafen` | 🤐 / 👂 {time} **{displayname}** was server-deafened / server-undeafened |

## Commands

All under `[p]vclog`, usable by server admins or members with Manage Server:

| Command | What it does |
| :--- | :--- |
| `enable` / `disable` | Turn logging on or off for the server (off by default) |
| `mode [mode]` | Set or view display mode (`small`, `normal`, `embed-small`, `embed`) with live preview |
| `channel [channel]` | Set a dedicated text channel for voice logs (omit to disable) |
| `voicechat <true/false>` | Toggle posting logs in voice channels' own text chats |
| `event <event> <true/false>` | Toggle one event |
| `template <event> [text]` | Custom message; no text restores the default |
| `author [name]` | Post through a webhook under this name; empty posts as the bot |
| `icon [url]` | Webhook avatar; `{avatar}` uses the member's avatar |
| `ignore <voice channel>` | Exclude / re-include a channel |
| `ignorebots <true/false>` | Skip bots (on by default) |
| `settings` | Show everything, including the placeholder list |

### Placeholders

`{username}` `{displayname}` `{userid}` `{mention}` `{avatar}` `{oldChannelName}`
`{oldChannelId}` `{newChannelName}` `{newChannelId}` `{guildName}` `{guildId}`
`{now}` `{time}` `{relative}` `{date}`

- `{time}`: Local short time (e.g. `13:45`)
- `{now}`: Local full timestamp (e.g. `November 12, 2026 1:45 PM`)
- `{relative}`: Relative time (e.g. `2 minutes ago`)
- `{date}`: Short date (e.g. `12/11/2026`)
- `{mention}`: `<@userid>` (if an interactive user pill is desired)
