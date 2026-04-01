# Agent Knowledge Base: UEVR Webhooks Cog

A listener and bridge for UEVR-related external update webhooks.

## 🏗️ Core Features
- **Webhook Endpoint**: Hosts a listener to receive raw JSON data from external UEVR build systems or tracking sites.
- **Rich Notifications**: Formats received data into structured Discord Embeds.
- **Update Tracking**: Monitors version strings and build IDs to notify guilds of new UEVR releases or patches.

## 🛠️ Implementation Details
- **Red Webhook Integration**: Often used to bridge specialized API feedback (like GitHub actions or CI) to community discord channels.
- **Formatting Logic**: Specialized in technical release notes, diffs, and build environment summaries.
- **Permission Mapping**: Allows admins to restrict which outgoing channels receive different types of UEVR update feeds.
