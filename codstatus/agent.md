# Agent Knowledge Base: COD Status Cog

A status monitoring bridge for Call of Duty (Activision).

## 🏗️ Core Features
- **Activision API**: Uses the internal `activision/` module to communicate with Call of Duty services.
- **Regex Parsing**: Leverages `regex_utils.py` for advanced string matching across game titles and user IDs.
- **Status Reporting**: Dynamically updates the bot's Discord presence and channel messages based on Call of Duty server stability or player status.

## 🛠️ Implementation Details
- **pcx_lib**: Dependent on `pcx_lib.py` for shared library functions.
- **Game ID Maps**: Maintains mapping between various Call of Duty game versions (e.g., MW, WZ, VG) and their respective API identifiers.
- **Rate-Limiting**: Implements basic interval-based polling to stay within Activision's undocumented rate limits.
