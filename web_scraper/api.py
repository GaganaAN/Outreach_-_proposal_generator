"""
Standalone FastAPI app for the web_scraper module.

Run it:
    cd swanson-engine-and-apis
    uvicorn web_scraper.api:app --reload --port 9000

Swagger UI:
    http://localhost:9000/docs

Four endpoints:
    POST /scraper/search            — search only (no crawling)
    POST /scraper/crawl             — crawl a single URL
    POST /scraper/crawl-many        — crawl a list of URLs concurrently
    POST /scraper/search-and-scrape — full pipeline (search + crawl)
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from web_scraper.filter import ContentFilter
from web_scraper.scraper import WebScraper
from web_scraper.searcher import Searcher

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Web Scraper API",
    description=(
        "Standalone scraping API — search via SearXNG, crawl pages with "
        "Playwright/crawl4ai, and optionally extract structured data via Azure OpenAI."
    ),
    version="1.0.0",
)


# ── Request / Response models ──────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str = Field(..., description="Search query string", example="Vitamin C 1000mg supplement")
    max_results: int = Field(5, ge=1, le=20, description="Max URLs to return")
    max_pages: int = Field(2, ge=1, le=5, description="How many SearXNG result pages to fetch")
    min_score: float = Field(0.0, ge=0.0, le=1.0, description="Minimum SearXNG score (0 = no filter)")
    apply_url_filter: bool = Field(True, description="Run the URL relevance filter")


class SearchResultItem(BaseModel):
    url: str
    title: Optional[str]
    snippet: Optional[str]
    score: Optional[float]
    relevance_score: Optional[float]


class SearchResponse(BaseModel):
    query: str
    total: int
    results: List[SearchResultItem]


class CrawlRequest(BaseModel):
    url: str = Field(
        ...,
        description="URL to crawl",
        example="https://www.iherb.com/pr/now-foods-vitamin-c-1000-mg-250-tablets/671",
    )
    include_full_content: bool = Field(
        False,
        description="Set true to include the complete page Markdown in the response (can be large)",
    )
    extraction_schema: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "JSON Schema properties dict for LLM-based extraction. "
            "Requires Azure OpenAI env vars. Omit to get raw Markdown only."
        ),
        example={
            "title":       {"type": "string", "description": "Product name"},
            "description": {"type": "string", "description": "Full product description"},
            "price":       {"type": "string", "description": "Price with currency symbol"},
        },
    )
    extraction_instruction: Optional[str] = Field(
        None,
        description="Plain-English instruction for the LLM when extraction_schema is set.",
        example="Extract the product title, full description, and price from this page.",
    )


class CrawlResponse(BaseModel):
    url: str
    success: bool
    content_preview: str = Field(description="First 500 characters of page Markdown")
    content: Optional[str] = Field(None, description="Full page Markdown (only when include_full_content=true)")
    content_length: int
    extracted_data: Dict[str, Any]
    time_taken: float
    error: Optional[str]


class CrawlManyRequest(BaseModel):
    urls: List[str] = Field(
        ...,
        min_items=1,
        max_items=10,
        description="List of URLs to crawl concurrently (max 10)",
        example=[
            "https://www.iherb.com/pr/now-foods-vitamin-c-1000-mg-250-tablets/671",
            "https://www.vitacost.com/now-vitamin-c-1000mg",
        ],
    )
    extraction_schema: Optional[Dict[str, Any]] = Field(
        None,
        description="Same as /crawl — optional LLM extraction schema",
    )
    extraction_instruction: Optional[str] = None
    max_concurrent: int = Field(3, ge=1, le=5, description="Max parallel crawls")
    include_full_content: bool = Field(False, description="Include full Markdown in each result")


class CrawlManyResponse(BaseModel):
    total: int
    success_count: int
    failed_count: int
    results: List[CrawlResponse]


class SearchAndScrapeRequest(BaseModel):
    query: str = Field(
        ...,
        description=(
            "Search query. Supports site-scoped queries like: "
            "site:iherb.com \"Vitamin C 1000mg\""
        ),
        example="Vitamin C 1000mg supplement iherb",
    )
    max_urls: int = Field(3, ge=1, le=10, description="Max URLs to search and crawl")
    max_pages: int = Field(2, ge=1, le=5, description="SearXNG result pages to fetch")
    apply_url_filter: bool = Field(True, description="Run the URL relevance filter before crawling")
    extraction_schema: Optional[Dict[str, Any]] = Field(
        None,
        description="Optional LLM extraction schema (requires Azure OpenAI env vars)",
        example={
            "title":             {"type": "string", "description": "Product name"},
            "description":       {"type": "string", "description": "Full product description"},
            "nutritional_facts": {"type": "string", "description": "Nutritional information"},
            "price":             {"type": "string", "description": "Price with currency"},
        },
    )
    extraction_instruction: Optional[str] = Field(
        None,
        example="Extract product title, description, nutritional facts, and price.",
    )
    include_full_content: bool = Field(False, description="Include full Markdown in each result")
    trusted_domains: Optional[List[str]] = Field(
        None,
        description="Domains that get a relevance score bonus in the filter",
        example=["iherb.com", "vitacost.com", "swansonvitamins.com"],
    )


class SearchAndScrapeResponse(BaseModel):
    query: str
    total_searched: int
    success_count: int
    failed_count: int
    scraped_at: str
    results: List[CrawlResponse]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _to_crawl_response(result, include_full_content: bool = False) -> CrawlResponse:
    return CrawlResponse(
        url=result.url,
        success=result.success,
        content_preview=result.content[:500] if result.content else "",
        content=result.content if include_full_content else None,
        content_length=len(result.content),
        extracted_data=result.extracted_data,
        time_taken=result.time_taken,
        error=result.error or None,
    )


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.post(
    "/scraper/search",
    response_model=SearchResponse,
    summary="Search only — no crawling",
    description=(
        "Queries SearXNG and returns ranked URLs. "
        "Apply the URL relevance filter to drop low-quality results."
    ),
)
async def search(body: SearchRequest):
    """
    Search SearXNG and return ranked URLs.
    No pages are crawled — use **/scraper/search-and-scrape** for that.
    """
    content_filter = ContentFilter() if body.apply_url_filter else None
    searcher = Searcher(content_filter=content_filter)

    results = await searcher.search(
        query=body.query,
        max_results=body.max_results,
        max_pages=body.max_pages,
        min_score=body.min_score,
        apply_filter=body.apply_url_filter,
    )

    from web_scraper.models import SearchError
    if isinstance(results, SearchError):
        raise HTTPException(status_code=502, detail=f"SearXNG error: {results.error}")

    return SearchResponse(
        query=body.query,
        total=len(results),
        results=[
            SearchResultItem(
                url=r.url,
                title=r.title,
                snippet=r.snippet,
                score=r.score,
                relevance_score=r.relevance_score,
            )
            for r in results
        ],
    )


@app.post(
    "/scraper/crawl",
    response_model=CrawlResponse,
    summary="Crawl a single URL",
    description=(
        "Load a URL in a stealth Chromium browser and return its Markdown content. "
        "Optionally extract structured JSON via Azure OpenAI by providing an extraction_schema."
    ),
)
async def crawl_single(body: CrawlRequest):
    """
    Crawl one URL.

    - Without ``extraction_schema``: returns raw page Markdown.
    - With ``extraction_schema``: also returns ``extracted_data`` JSON (needs Azure OpenAI).
    """
    scraper = WebScraper(
        extraction_schema=body.extraction_schema,
        extraction_instruction=body.extraction_instruction,
    )
    result = await scraper.scrape_url(body.url)
    return _to_crawl_response(result, include_full_content=body.include_full_content)


@app.post(
    "/scraper/crawl-many",
    response_model=CrawlManyResponse,
    summary="Crawl multiple URLs concurrently",
    description="Crawl a list of URLs in parallel (max 10). Returns Markdown + optional LLM extraction.",
)
async def crawl_many(body: CrawlManyRequest):
    """
    Crawl up to 10 URLs concurrently.
    """
    if len(body.urls) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 URLs per request.")

    scraper = WebScraper(
        extraction_schema=body.extraction_schema,
        extraction_instruction=body.extraction_instruction,
        max_concurrent_crawls=body.max_concurrent,
    )
    results = await scraper.scrape_urls(body.urls)
    responses = [_to_crawl_response(r, include_full_content=body.include_full_content) for r in results]

    return CrawlManyResponse(
        total=len(responses),
        success_count=sum(1 for r in responses if r.success),
        failed_count=sum(1 for r in responses if not r.success),
        results=responses,
    )


@app.post(
    "/scraper/search-and-scrape",
    response_model=SearchAndScrapeResponse,
    summary="Full pipeline — search then crawl all results",
    description=(
        "Runs the complete pipeline: "
        "SearXNG search → URL filter → concurrent crawl → optional LLM extraction."
    ),
)
async def search_and_scrape(body: SearchAndScrapeRequest):
    """
    Full scraping pipeline.

    1. Searches SearXNG for ``query``.
    2. Filters URLs by relevance (if ``apply_url_filter=true``).
    3. Crawls the top ``max_urls`` results concurrently.
    4. Optionally extracts structured JSON via Azure OpenAI.

    **Site-scoped query example:**  ``site:iherb.com "Vitamin C 1000mg"``
    """
    content_filter = (
        ContentFilter(trusted_domains=body.trusted_domains or [])
        if body.apply_url_filter
        else None
    )
    scraper = WebScraper(
        extraction_schema=body.extraction_schema,
        extraction_instruction=body.extraction_instruction,
        content_filter=content_filter,
    )
    output = await scraper.search_and_scrape(
        query=body.query,
        max_urls=body.max_urls,
        max_pages=body.max_pages,
    )

    return SearchAndScrapeResponse(
        query=output.query,
        total_searched=len(output.results),
        success_count=output.total_success,
        failed_count=output.total_failed,
        scraped_at=output.scraped_at,
        results=[_to_crawl_response(r, include_full_content=body.include_full_content) for r in output.results],
    )


@app.get("/scraper/health", summary="Health check")
async def health():
    """Check whether the scraper API is running."""
    from web_scraper.config import scraper_settings
    return JSONResponse({
        "status": "ok",
        "searxng_url": scraper_settings.SEARXNG_BASE_URL,
        "llm_configured": scraper_settings.llm_configured(),
    })
