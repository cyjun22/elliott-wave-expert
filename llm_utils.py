"""
LLM Utilities - Shared helpers for LLM integration
===================================================
Centralizes JSON parsing, client management, and common LLM patterns.
"""

import os
import re
import json
from typing import Dict, Optional, Tuple

from openai import AzureOpenAI


def safe_parse_json(content: str, fallback: Dict = None) -> Tuple[Dict, bool]:
    """
    Robust JSON parsing with multiple fallback strategies.

    Args:
        content: Raw LLM response string
        fallback: Default value on failure

    Returns:
        Tuple of (parsed_dict, success_flag)
    """
    if fallback is None:
        fallback = {}

    # Strategy 1: Extract JSON from markdown code blocks
    patterns = [
        r'```json\s*([\s\S]*?)```',  # ```json ... ```
        r'```\s*([\s\S]*?)```',       # ``` ... ```
        r'\{[\s\S]*\}',               # Raw JSON object
    ]

    for pattern in patterns:
        match = re.search(pattern, content)
        if match:
            json_str = match.group(1) if '```' in pattern else match.group(0)
            try:
                return json.loads(json_str.strip()), True
            except json.JSONDecodeError:
                continue

    # Strategy 2: Try direct parsing
    try:
        return json.loads(content.strip()), True
    except json.JSONDecodeError:
        pass

    # Strategy 3: Basic repair (trailing commas, single quotes)
    try:
        repaired = content.strip()
        repaired = re.sub(r',\s*}', '}', repaired)  # Remove trailing commas
        repaired = re.sub(r',\s*]', ']', repaired)
        repaired = repaired.replace("'", '"')       # Single to double quotes
        return json.loads(repaired), True
    except json.JSONDecodeError:
        pass

    return fallback, False


def get_azure_openai_client() -> Optional[AzureOpenAI]:
    """
    Create or return a shared AzureOpenAI client.

    Uses environment variables:
        AZURE_OPENAI_ENDPOINT
        AZURE_OPENAI_API_KEY

    Returns:
        AzureOpenAI client instance, or None if credentials missing.
    """
    endpoint = os.environ.get('AZURE_OPENAI_ENDPOINT')
    api_key = os.environ.get('AZURE_OPENAI_API_KEY')

    if not endpoint or not api_key:
        return None

    return AzureOpenAI(
        azure_endpoint=endpoint,
        api_key=api_key,
        api_version='2024-02-15-preview'
    )


# Module-level shared client (lazy singleton)
_shared_client: Optional[AzureOpenAI] = None


def get_shared_azure_client() -> Optional[AzureOpenAI]:
    """
    Return a module-level shared AzureOpenAI client.
    Created on first call, reused thereafter.
    """
    global _shared_client
    if _shared_client is None:
        _shared_client = get_azure_openai_client()
    return _shared_client
