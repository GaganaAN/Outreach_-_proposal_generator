"""
Loads the company knowledge base file and caches it in memory.
The KB is read once on first access and reused for all subsequent LLM calls.
"""
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_KB_PATH = Path(__file__).parent.parent / "kb" / "knowledge base.txt"
_kb_cache: Optional[str] = None


def get_company_kb() -> str:
    """Return the full knowledge base text, loading from disk on first call."""
    global _kb_cache
    if _kb_cache is not None:
        return _kb_cache

    if not _KB_PATH.exists():
        logger.warning(f"[KB] Knowledge base file not found at {_KB_PATH} — using empty profile")
        _kb_cache = ""
        return _kb_cache

    try:
        _kb_cache = _KB_PATH.read_text(encoding="utf-8").strip()
        logger.info(f"[KB] Loaded company knowledge base ({len(_kb_cache):,} chars) from {_KB_PATH.name}")
    except Exception as e:
        logger.error(f"[KB] Failed to read knowledge base: {e}")
        _kb_cache = ""

    return _kb_cache
