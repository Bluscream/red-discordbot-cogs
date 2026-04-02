from dataclasses import dataclass, field
from typing import Optional, Any
from uuid import UUID
import time

@dataclass
class SynchraSession:
    """Represents an active monitoring session for a Synchra channel."""
    channel_uuid: UUID
    display_name: str
    
    # Platform mapping (for HLS and fallback monitoring)
    platform: str
    handle: str
    
    # Discord targets
    text_channel_id: int
    voice_channel_id: Optional[int] = None
    webhook_url: Optional[str] = None
    
    # Feature states
    voice_enabled: bool = True
    chat_enabled: bool = True
    
    # Live status
    is_live: bool = False
    last_status_check: float = 0.0
    last_live: float = 0.0
    
    # Voice bridge state
    voice_client: Any = None
    hls_url: Optional[str] = None
    
    # Notification state
    last_notified_is_live: Optional[bool] = None
    last_notified_title: str = ""
    last_notified_game: str = ""
    avatar_url: str = ""

    def __post_init__(self):
        self.last_status_check = time.time()
