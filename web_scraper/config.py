import os

from dotenv import load_dotenv

load_dotenv()


class ScraperSettings:
    # ── SearXNG ────────────────────────────────────────────────────────────────
    SEARXNG_BASE_URL: str = os.getenv("SEARXNG_BASE_URL", "http://localhost:8080/search")
    WEB_SEARCH_TIMEOUT: int = int(os.getenv("WEB_SEARCH_TIMEOUT", "30"))
    WEB_SEARCH_MAX_RESULTS: int = int(os.getenv("WEB_SEARCH_MAX_RESULTS", "5"))
    WEB_SEARCH_MAX_PAGES: int = int(os.getenv("WEB_SEARCH_MAX_PAGES", "2"))
    # 0.0 = no score filter (accept everything SearXNG returns)
    WEB_SEARCH_MIN_SCORE: float = float(os.getenv("WEB_SEARCH_MIN_SCORE", "0.0"))

    # ── Browser / Playwright ───────────────────────────────────────────────────
    PAGE_TIMEOUT_MS: int = int(os.getenv("WEB_SCRAP_PAGE_TIMEOUT_MS", "30000"))
    STEALTH_DELAY_SECONDS: int = int(os.getenv("WEB_SCRAP_STEALTH_DELAY_SECONDS", "1"))
    DYNAMIC_CONTENT_DELAY_SECONDS: int = int(os.getenv("WEB_SCRAP_DYNAMIC_CONTENT_DELAY_SECONDS", "2"))
    MAX_RETRIES: int = int(os.getenv("WEB_SCRAP_MAX_RETRIES", "2"))

    # ── Azure OpenAI (optional — only needed for LLM extraction mode) ──────────
    AZURE_OPENAI_ENDPOINT: str = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    AZURE_OPENAI_API_KEY: str = os.getenv("AZURE_OPENAI_API_KEY", "")
    AZURE_OPENAI_API_VERSION: str = os.getenv("AZURE_OPENAI_API_VERSION", "")
    AZURE_OPENAI_DEPLOYMENT_NAME: str = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "")

    # ── Concurrency ────────────────────────────────────────────────────────────
    MAX_CONCURRENT_CRAWLS: int = int(os.getenv("MAX_CONCURRENT_CRAWLS", "3"))

    def llm_configured(self) -> bool:
        return bool(
            self.AZURE_OPENAI_ENDPOINT
            and self.AZURE_OPENAI_API_KEY
            and self.AZURE_OPENAI_DEPLOYMENT_NAME
        )


scraper_settings = ScraperSettings()
