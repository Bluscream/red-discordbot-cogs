"""
AutoMod compatibility layer for discord.py versions that don't have built-in AutoMod support.

This module provides the necessary enums and helper functions to work with Discord's
AutoMod API across different versions of discord.py.

Based on discord.py 2.6+ implementation.
MIT License - Copyright (c) 2015-present Rapptz
"""

from enum import Enum
from typing import Any, Dict, Optional

__all__ = (
    'AutoModRuleTriggerType',
    'AutoModRuleEventType',
    'AutoModRuleActionType',
    'AutoModAction',
    'AutoModActionMetadata',
    'AutoModTrigger',
)


class AutoModRuleTriggerType(Enum):
    """Represents the type of trigger for an AutoMod rule."""
    keyword = 1
    harmful_link = 2  # Deprecated, replaced by keyword
    spam = 3
    keyword_preset = 4
    mention_spam = 5
    member_profile = 6


class AutoModRuleEventType(Enum):
    """Represents the event type that triggers an AutoMod rule."""
    message_send = 1
    member_update = 2


class AutoModRuleActionType(Enum):
    """Represents the type of action an AutoMod rule can take."""
    block_message = 1
    send_alert_message = 2
    timeout = 3
    block_member_interactions = 4


class AutoModActionMetadata:
    """
    Represents metadata for an AutoMod action.
    
    Attributes
    ----------
    channel_id : Optional[int]
        The channel ID to send alerts to (for send_alert_message action type).
    custom_message : Optional[str]
        Custom message to show when blocking (for block_message action type).
    duration_seconds : Optional[int]
        Timeout duration in seconds (for timeout action type).
    """
    
    __slots__ = ('channel_id', 'custom_message', 'duration_seconds')
    
    def __init__(
        self,
        *,
        channel_id: Optional[int] = None,
        custom_message: Optional[str] = None,
        duration_seconds: Optional[int] = None
    ):
        self.channel_id = channel_id
        self.custom_message = custom_message
        self.duration_seconds = duration_seconds
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metadata to API payload format."""
        data = {}
        if self.channel_id is not None:
            data['channel_id'] = str(self.channel_id)
        if self.custom_message is not None:
            data['custom_message'] = self.custom_message
        if self.duration_seconds is not None:
            data['duration_seconds'] = self.duration_seconds
        return data


class AutoModAction:
    """
    Represents an AutoMod action.
    
    Attributes
    ----------
    type : AutoModRuleActionType or int
        The type of action.
    metadata : Optional[AutoModActionMetadata]
        The metadata for this action.
    """
    
    __slots__ = ('type', 'metadata')
    
    def __init__(
        self,
        *,
        type: Any,  # Can be enum or int
        metadata: Optional[AutoModActionMetadata] = None
    ):
        self.type = type
        self.metadata = metadata
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert action to API payload format."""
        data: Dict[str, Any] = {
            'type': self.type.value if hasattr(self.type, 'value') else self.type,
            'metadata': self.metadata.to_dict() if self.metadata else {}
        }
        return data
    
    def __repr__(self) -> str:
        return f'<AutoModAction type={self.type}>'


class AutoModTrigger:
    """
    Represents a trigger for an AutoMod rule.
    Matches discord.py v2.6.3 structure where properties are directly on the trigger.
    
    Attributes
    ----------
    type : AutoModRuleTriggerType or int
        The type of trigger.
    keyword_filter : list[str]
        List of keywords to filter (for keyword trigger type).
    regex_patterns : list[str]
        List of regex patterns to match (for keyword trigger type).
    allow_list : list[str]
        List of keywords to allow/exempt (for keyword trigger type).
    presets : list[int]
        List of preset keyword filters (for keyword_preset trigger type).
    mention_limit : int
        Maximum mentions allowed (for mention_spam trigger type).
    mention_raid_protection : bool
        Whether mention raid protection is enabled (for mention_spam trigger type).
    """
    
    __slots__ = (
        'type',
        'keyword_filter',
        'regex_patterns',
        'allow_list',
        'presets',
        'mention_limit',
        'mention_raid_protection'
    )
    
    def __init__(
        self,
        *,
        type: Any,  # Can be enum or int
        keyword_filter: Optional[list] = None,
        regex_patterns: Optional[list] = None,
        allow_list: Optional[list] = None,
        presets: Optional[list] = None,
        mention_limit: Optional[int] = None,
        mention_raid_protection: Optional[bool] = None
    ):
        self.type = type
        self.keyword_filter = keyword_filter or []
        self.regex_patterns = regex_patterns or []
        self.allow_list = allow_list or []
        self.presets = presets or []
        self.mention_limit = mention_limit or 0
        self.mention_raid_protection = mention_raid_protection or False
    
    def to_metadata_dict(self) -> Optional[Dict[str, Any]]:
        """Convert trigger metadata to API payload format."""
        data = {}
        if self.keyword_filter:
            data['keyword_filter'] = self.keyword_filter
        if self.regex_patterns:
            data['regex_patterns'] = self.regex_patterns
        if self.allow_list:
            data['allow_list'] = self.allow_list
        if self.presets:
            data['presets'] = self.presets
        if self.mention_limit:
            data['mention_total_limit'] = self.mention_limit
        if self.mention_raid_protection:
            data['mention_raid_protection_enabled'] = self.mention_raid_protection
        return data if data else None
    
    def __repr__(self) -> str:
        return f'<AutoModTrigger type={self.type}>'


# AutoModTriggerMetadata is not a separate class in discord.py v2.6.3
# All metadata properties are directly on AutoModTrigger


def get_automod_enums():
    """
    Try to import AutoMod enums from discord.py.
    Falls back to compatibility enums if not available.
    
    Returns
    -------
    tuple
        A tuple of (AutoModEventType, AutoModTriggerType, AutoModActionType, has_native)
        where has_native indicates if native discord.py enums were used.
    """
    try:
        from discord import (
            AutoModEventType as NativeEventType,
            AutoModTriggerType as NativeTriggerType,
            AutoModActionType as NativeActionType
        )
        return (NativeEventType, NativeTriggerType, NativeActionType, True)
    except ImportError:
        return (AutoModRuleEventType, AutoModRuleTriggerType, AutoModRuleActionType, False)


def get_automod_classes():
    """
    Try to import AutoMod classes from discord.py.
    Falls back to compatibility classes if not available.
    
    Returns
    -------
    tuple
        A tuple of (AutoModAction, AutoModActionMetadata, AutoModTrigger, has_native)
        where has_native indicates if native discord.py classes were used.
    """
    try:
        from discord import (
            AutoModAction as NativeAction,
            AutoModActionMetadata as NativeActionMetadata,
            AutoModTrigger as NativeTrigger
        )
        return (NativeAction, NativeActionMetadata, NativeTrigger, True)
    except ImportError:
        return (AutoModAction, AutoModActionMetadata, AutoModTrigger, False)
