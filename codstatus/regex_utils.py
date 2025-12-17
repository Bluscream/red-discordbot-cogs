"""Regex utilities for parsing patterns with flags."""

import re
from typing import Tuple


class RegexParser:
    """Parser for regex patterns with JavaScript-style flags (e.g., pattern/i, pattern/ig)."""

    @staticmethod
    def parse_flags(pattern: str) -> Tuple[str, int]:
        """Parse regex flags from pattern string (e.g., 'pattern/i' or 'pattern/ig').
        
        Args:
            pattern: Pattern string that may end with /flags
        
        Returns:
            Tuple of (cleaned_pattern, flags_int)
            Default flags are 0 (case-sensitive) if no flags specified
        """
        # Check if pattern ends with /flags format
        if '/' in pattern and pattern.rindex('/') > 0:
            # Find the last / that might be a flag separator
            parts = pattern.rsplit('/', 1)
            if len(parts) == 2 and parts[1]:
                potential_flags = parts[1].lower()
                # Check if it's all valid flag characters
                if all(c in 'igmsuvx' for c in potential_flags):
                    clean_pattern = parts[0]
                    flags = 0
                    
                    # Parse individual flags
                    if 'i' in potential_flags:
                        flags |= re.IGNORECASE
                    if 'm' in potential_flags:
                        flags |= re.MULTILINE
                    if 's' in potential_flags:
                        flags |= re.DOTALL
                    if 'u' in potential_flags:
                        flags |= re.UNICODE
                    if 'v' in potential_flags:
                        flags |= re.VERBOSE
                    if 'x' in potential_flags:
                        flags |= re.VERBOSE  # x is same as v in Python
                    # 'g' (global) is ignored - not applicable in Python
                    
                    return clean_pattern, flags
        
        # No flags found, return pattern as-is with default flags (0 = case-sensitive)
        return pattern, 0

    @staticmethod
    def compile_pattern(pattern: str) -> re.Pattern:
        """Compile a regex pattern, parsing flags if present.
        
        Args:
            pattern: Pattern string that may include /flags
        
        Returns:
            Compiled regex pattern
        
        Raises:
            re.error: If the pattern is invalid
        """
        clean_pattern, flags = RegexParser.parse_flags(pattern)
        return re.compile(clean_pattern, flags)

    @staticmethod
    def validate_pattern(pattern: str) -> Tuple[bool, str]:
        """Validate a regex pattern.
        
        Args:
            pattern: Pattern string to validate
        
        Returns:
            Tuple of (is_valid, error_message)
            If valid, error_message is empty string
        """
        try:
            RegexParser.compile_pattern(pattern)
            return True, ""
        except re.error as e:
            return False, str(e)
