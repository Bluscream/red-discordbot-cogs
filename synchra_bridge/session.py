from dataclasses import dataclass, field
from typing import Optional, Any, List
from uuid import UUID
import time

@dataclass
class SynchraSession:
    """Represents a monitored Synchra channel session."""
    channel_uuid: UUID
    display_name: str
    
    # Discord Integration
    text_channel_id: Optional[int] = None
    voice_channel_id: Optional[int] = None
    webhook_url: Optional[str] = None
    
    # Feature Toggles
    voice_enabled: bool = True
    chat_enabled: bool = True
    
    # Runtime State
    is_live: bool = False
    last_live: float = 0
    last_status_check: float = 0
    last_notified_is_live: Optional[bool] = None
    
    # Multi-Platform Support
    providers: List[Any] = field(default_factory=list) # List[ChannelProvider]
    hls_url: Optional[str] = None
    voice_client: Optional[Any] = None
    
    # Last broadcast cache
    last_notified_title: str = ""
    last_notified_game: str = ""
    avatar_url: str = ""

    def __post_init__(self):
        self.last_status_check = time.time()

    @property
    def platform_names(self) -> List[str]:
        """Returns a list of platform names (e.g., ['Twitch', 'YouTube'])."""
        return [getattr(p.provider, 'value', str(p.provider)).capitalize() for p in self.providers]

    @property
    def is_currently_live(self) -> bool:
        """Returns True if any associated provider is currently live."""
        return any(getattr(p, 'is_live', False) for p in self.providers)
