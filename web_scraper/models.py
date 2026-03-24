from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field


# ── Search ─────────────────────────────────────────────────────────────────────

class SearchResult(BaseModel):
    """A single URL result returned by SearXNG."""
    url: str
    title: Optional[str] = None
    snippet: Optional[str] = None
    score: Optional[float] = None
    engine: Optional[str] = None
    engines: Optional[List[str]] = None
    published_date: Optional[str] = None
    relevance_score: Optional[float] = None
    success: bool = True


class SearchError(BaseModel):
    """Returned when the SearXNG call itself fails."""
    query: str
    error: str
    extracted_at: datetime = Field(default_factory=datetime.now)
    success: bool = False


# ── Crawl ──────────────────────────────────────────────────────────────────────

@dataclass
class CrawlResult:
    """Result of crawling a single URL."""
    url: str
    success: bool
    # Raw markdown text of the page (always populated on success)
    content: str = ""
    # Structured JSON extracted by LLM (only when extraction_schema is provided)
    extracted_data: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    time_taken: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


# ── Scrape output ──────────────────────────────────────────────────────────────

@dataclass
class ScrapeOutput:
    """Aggregated output of a full search-and-scrape run."""
    query: str
    results: List[CrawlResult] = field(default_factory=list)
    scraped_at: str = field(default_factory=lambda: datetime.now().isoformat())
    total_success: int = 0
    total_failed: int = 0

    def successful(self) -> List[CrawlResult]:
        return [r for r in self.results if r.success]

    def failed(self) -> List[CrawlResult]:
        return [r for r in self.results if not r.success]


# ── Filter internals ───────────────────────────────────────────────────────────

@dataclass
class FilterRule:
    """A dynamically learned URL filter rule."""
    pattern: str
    rule_type: str          # "url" | "title"
    confidence: float = 0.5
    usage_count: int = 0
    context_tags: Set[str] = field(default_factory=set)
