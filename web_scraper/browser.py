"""
Stealth browser configuration.

Builds a Playwright BrowserConfig that looks like a real human browser by:
  - Randomising the User-Agent string (Chrome / Edge, desktop)
  - Pairing matching sec-ch-ua client-hint headers
  - Randomising the viewport resolution
  - Disabling automation-detection flags

Also provides a RetryManager for exponential-backoff retries.
"""

import asyncio
import random
from typing import Dict, Tuple

from crawl4ai import BrowserConfig
from crawl4ai.user_agent_generator import UserAgentGenerator


# ── Headers ────────────────────────────────────────────────────────────────────

def _stealth_headers(client_hints: str) -> Dict[str, str]:
    return {
        "sec-ch-ua":                client_hints,
        "sec-ch-ua-mobile":         "?0",
        "sec-ch-ua-platform":       '"Linux"',
        "sec-fetch-dest":           "document",
        "sec-fetch-mode":           "navigate",
        "sec-fetch-site":           "none",
        "sec-fetch-user":           "?1",
        "upgrade-insecure-requests": "1",
        "accept":                   (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "accept-language":          "en-US,en;q=0.9",
        "accept-encoding":          "gzip, deflate, br",
        "cache-control":            "no-cache",
        "dnt":                      "1",
    }


_RESOLUTIONS: Tuple[Tuple[int, int], ...] = (
    (1920, 1080), (1366, 768), (1536, 864),
    (1440, 900),  (1280, 720), (1600, 900),
    (2560, 1440),
)


# ── Anti-detection ─────────────────────────────────────────────────────────────

class _UAPool:
    """Keeps a pool of used user-agents to avoid repeating them."""

    def __init__(self):
        self._gen = UserAgentGenerator()
        self._used: set = set()

    def next(self) -> Tuple[str, str]:
        for _ in range(10):
            ua, hints = self._gen.generate_with_client_hints(
                device_type="desktop",
                browser_type=random.choice(["chrome", "edge"]),
                num_browsers=3,
            )
            if ua not in self._used:
                break
        self._used.add(ua)
        if len(self._used) > 100:
            self._used = set(list(self._used)[-50:])
        return ua, hints


_ua_pool = _UAPool()


def build_stealth_config() -> BrowserConfig:
    """
    Return a BrowserConfig that mimics a real desktop browser.
    Call this once per crawl session.
    """
    ua, hints = _ua_pool.next()
    w, h = random.choice(_RESOLUTIONS)
    return BrowserConfig(
        headless=True,
        user_agent=ua,
        headers=_stealth_headers(hints),
        viewport_width=w,
        viewport_height=h,
        java_script_enabled=True,
        ignore_https_errors=True,
        extra_args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-web-security",
            "--disable-blink-features=AutomationControlled",
            f"--window-size={w},{h}",
            "--disable-automation",
        ],
    )


# ── Retry manager ──────────────────────────────────────────────────────────────

class RetryManager:
    """
    Runs an async crawl with exponential-backoff retries.

    Delay formula:  base_delay * (2 ** attempt) + random jitter in [0, 1)
    """

    def __init__(self, max_retries: int = 2, base_delay: float = 1.0):
        self.max_retries = max_retries
        self.base_delay = base_delay

    async def run(self, crawler, url: str, config) -> object:
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                result = await crawler.arun(url=url, config=config)
                if result.success:
                    return result
                last_error = result.error_message
            except Exception as exc:
                last_error = str(exc)

            if attempt < self.max_retries:
                delay = self.base_delay * (2 ** attempt) + random.random()
                await asyncio.sleep(delay)

        # Return a sentinel failure object
        from crawl4ai.models import AsyncCrawlResponse
        return AsyncCrawlResponse(
            url=url,
            success=False,
            error_message=(
                f"Failed after {self.max_retries + 1} attempt(s). "
                f"Last error: {last_error}"
            ),
        )
