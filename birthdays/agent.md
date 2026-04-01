# Agent Knowledge Base: Birthdays Cog

A specialized birthday management system for Red.

## 🏗️ Core Features
- **Discord Scheduled Events**: Integrates with standard Discord Scheduled Events to announce birthdays.
- **Date Formatting**: Supports multiple date patterns using a centralized `date_formats` utility.
- **I18n (Localization)**: Uses the `Strings` class for translated user messages.

## 🛠️ Implementation Details
- **pcx_lib**: Dependent on `pcx_lib.py` for shared library functions.
- **Persistence**: Efficiently stores and retrieves user birthdates, using the guild-wide Scheduled Events as a public-facing notification layer.
- **Background Tasks**: Periodic checks to ensure birthdays are synced with active Discord events.
