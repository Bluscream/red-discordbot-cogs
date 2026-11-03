# Honeypot

Trap channels for spam bots and hacked accounts. Spam tools and compromised accounts post into
every channel they can see; members are told never to post in the trap. Whoever posts there is
softbanned (default) or banned the moment they do, and their recent messages disappear with them.

Behaviour follows [RiskyMH's Honeypot bot](https://honeypot.riskymh.dev) (docs, setup guide, tips,
FAQ and blog), reimplemented from scratch as a Red cog. Its code is AGPL-3.0 and none of it is
copied here.

## What happens on a trigger

1. A message in a honeypot channel (text channel or a voice/stage channel's chat). Slash commands
   used there count against the user who ran them. Bots, webhooks and system messages (joins,
   boosts, pins, AutoMod notices…) are ignored.
2. The message gets a 🍯 reaction (or is deleted at once with `ensure-msg-delete`).
3. Within a 2-second budget, before the ban: a DM explaining what happened and how to secure the
   account, the optional 1-hour timeout, and the optional forward of the message to the log.
4. **Softban** (ban + immediate unban, removes the last hour of messages, they can rejoin) or
   **ban** (with an Unban button in the log). `disabled` only reacts.
5. The server owner and Administrators are never actioned; a warning is logged instead and they
   get the DM as an example.
6. Log entry, Red modlog case, and the counter under the channel warning goes up (edits are
   throttled to one per 10 seconds per channel).
7. With `ensure-msg-delete`, 2 minutes later the cog searches for leftovers Discord missed during
   the ban and deletes them (guild message search; falls back to scanning recent history).

A deleted warning is reposted automatically; deleted trap or log channels are forgotten. Each
member is only processed once at a time, and DMs/reactions have their own rate limits so a spam
wave cannot exhaust the bot's global limits.

## Commands (`[p]honeypot`, alias `[p]hp`; admins or Manage Server)

| Command | |
| :--- | :--- |
| `status` | Settings plus a permission check (role order, channel permissions, experiments) |
| `create [name]` | New trap channel in the second postable slot near the top |
| `add <channel>` / `remove <channel>` | Watch / stop watching a channel (text or voice) |
| `action <softban\|ban\|disabled>` | What happens to a trigger |
| `logchannel [channel]` | Where actions and errors go |
| `experiment [name] [on/off]` | List or toggle experiments |
| `message <warning\|dm\|log> [text]` | Custom text; no text restores the default |
| `variables` / `defaults` / `preview <kind>` | Help for custom texts |
| `refresh` | Repost or update every warning |
| `rundaily` | Run the daily experiments now |

Warning and DM texts may end with up to four image URLs, one per line. Placeholders use
`{{double:braces}}`; the log text must contain `{{user:mention}}` or `{{user:id}}`.

## Experiments

| Name | Effect |
| :--- | :--- |
| `forward-message` | Forward the triggering message into the log |
| `reinvite` | Permanent rejoin invite in the DM (good with softban) |
| `no-warning-msg` | No warning, the channel looks empty |
| `no-dm` | Don't DM |
| `channel-warmer` | Daily send + delete so the channel looks active |
| `random-channel-name` / `random-channel-name-chaos` | Daily rename from a list / to random characters |
| `recreate-channel` | Daily recreate with a new ID (breaks anything referencing the old ID: AutoMod exemptions, onboarding) |
| `timeout-first` | 1-hour timeout before acting, so an instant rejoin stays muted |
| `only-recent-delete` | Delete the last 15 minutes instead of 1 hour |
| `ensure-msg-delete` | Delete the trigger at once and sweep leftovers after 2 minutes |

## Setup tips (from the Honeypot docs)

- Bot role above every member role; Ban Members, Manage Messages, Read Message History, plus
  Manage Channels / Create Invite / Moderate Members for the experiments that need them.
- Ordinary-looking name, near the top but not first, under a normal category, same slowmode and
  permissions as its neighbours, attachments allowed. Never an active channel.
- Several traps with different names, including one voice channel chat.
- Exclude the trap channels from AutoMod rules so AutoMod doesn't block the spam first.
- Test with an alt account: DM, action and log should all happen.
