"""
Page crawler — loads a URL with a real Chromium browser and returns its content.

Two extraction modes
--------------------
1. **Markdown mode** (default)
   Returns the full page text converted to Markdown.
   No LLM required.

2. **LLM extraction mode**
   Pass ``extraction_schema`` (a JSON Schema dict) and optionally
   ``extraction_instruction`` (a prompt string) to the ``Crawler``.
   The page Markdown is sent to Azure OpenAI and structured JSON is returned.

Retry
-----
Uses exponential backoff via ``RetryManager``.  Configure ``max_retries``
in ``ScraperSettings`` or pass it directly.
"""

import json
import logging
import time
from typing import Any, Dict, Optional

from crawl4ai import AsyncWebCrawler, CacheMode, CrawlerRunConfig
from crawl4ai.types import create_llm_config

from web_scraper.browser import RetryManager, build_stealth_config
from web_scraper.config import scraper_settings
from web_scraper.models import CrawlResult

logger = logging.getLogger(__name__)


def _has_dynamic_content(url: str) -> bool:
    """Heuristic: URLs containing SPA/AJAX signals need extra wait time."""
    signals = ["#", "?page=", "?tab=", "/react", "/angular", "/vue"]
    return any(s in url.lower() for s in signals)


class Crawler:
    """
    Crawls a single URL and returns a :class:`CrawlResult`.

    Parameters
    ----------
    extraction_schema:
        Optional JSON Schema dict describing the fields to extract via LLM.
        Example::

            {
                "title":       {"type": "string", "description": "Product name"},
                "description": {"type": "string", "description": "Full description"},
                "price":       {"type": "string", "description": "Price with currency"},
            }

    extraction_instruction:
        Plain-English instruction sent to the LLM along with the schema.
        Defaults to a generic extraction prompt when a schema is provided.

    max_retries:
        How many times to retry a failed crawl (default: from settings).
    """

    def __init__(
        self,
        extraction_schema: Optional[Dict[str, Any]] = None,
        extraction_instruction: Optional[str] = None,
        max_retries: int = None,
    ):
        self.extraction_schema = extraction_schema
        self.extraction_instruction = (
            extraction_instruction
            or "Extract the requested fields from the page content. Return only valid JSON."
        )
        self.max_retries = max_retries if max_retries is not None else scraper_settings.MAX_RETRIES

    def _build_llm_strategy(self):
        """Build an LLMExtractionStrategy if schema + Azure config are present."""
        if not self.extraction_schema:
            return None
        if not scraper_settings.llm_configured():
            logger.warning(
                "extraction_schema provided but Azure OpenAI is not configured. "
                "Falling back to markdown-only mode."
            )
            return None

        from crawl4ai import LLMExtractionStrategy

        llm_cfg = create_llm_config(
            provider=f"azure/{scraper_settings.AZURE_OPENAI_DEPLOYMENT_NAME}",
            api_token=scraper_settings.AZURE_OPENAI_API_KEY,
            base_url=scraper_settings.AZURE_OPENAI_ENDPOINT,
        )
        schema = {
            "type": "object",
            "properties": self.extraction_schema,
            "required": list(self.extraction_schema.keys()),
        }
        return LLMExtractionStrategy(
            llm_config=llm_cfg,
            schema=schema,
            temperature=0.0,
            verbose=False,
            extra_args={"api_version": scraper_settings.AZURE_OPENAI_API_VERSION},
            instruction=self.extraction_instruction,
        )

    def _build_run_config(self, delay: int, strategy) -> CrawlerRunConfig:
        return CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            word_count_threshold=50,
            page_timeout=scraper_settings.PAGE_TIMEOUT_MS,
            delay_before_return_html=delay,
            extraction_strategy=strategy,
        )

    async def crawl(self, url: str) -> CrawlResult:
        """
        Load ``url`` in a headless Chromium browser and return a :class:`CrawlResult`.

        The result always has ``content`` (Markdown text).
        ``extracted_data`` is populated only when an ``extraction_schema`` was
        provided and the LLM call succeeded.
        """
        start = time.time()
        delay = (
            scraper_settings.DYNAMIC_CONTENT_DELAY_SECONDS
            if _has_dynamic_content(url)
            else scraper_settings.STEALTH_DELAY_SECONDS
        )

        strategy = self._build_llm_strategy()
        browser_config = build_stealth_config()
        run_config = self._build_run_config(delay, strategy)
        retry = RetryManager(max_retries=self.max_retries)

        try:
            async with AsyncWebCrawler(config=browser_config) as crawler:
                raw = await retry.run(crawler, url, run_config)

                elapsed = round(time.time() - start, 2)

                if not raw.success:
                    return CrawlResult(
                        url=url,
                        success=False,
                        error=getattr(raw, "error_message", "Unknown error"),
                        time_taken=elapsed,
                    )

                content = raw.markdown or ""

                # ── LLM extraction ─────────────────────────────────────────────
                extracted: Dict[str, Any] = {}
                if strategy and raw.extracted_content:
                    try:
                        parsed = json.loads(raw.extracted_content)
                        extracted = parsed[0] if isinstance(parsed, list) and parsed else parsed
                    except (json.JSONDecodeError, IndexError) as exc:
                        logger.warning("LLM extraction JSON parse failed for %s: %s", url, exc)

                return CrawlResult(
                    url=url,
                    success=True,
                    content=content,
                    extracted_data=extracted,
                    time_taken=elapsed,
                    metadata=dict(getattr(raw, "metadata", {}) or {}),
                )

        except Exception as exc:
            logger.exception("Unexpected error crawling %s", url)
            return CrawlResult(
                url=url,
                success=False,
                error=str(exc),
                time_taken=round(time.time() - start, 2),
            )
