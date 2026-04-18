"""
StealthCrawler — stealth browser crawler for procurement sources (HigherGov, etc.)

Adapted from Scrapling/crawler_scrapling.py and Scrapling/links.py patterns.
Handles: authenticated sessions, Cloudflare / anti-bot bypass, JS-controlled
pagination, parallel sub-page scraping, and inline PDF extraction.

This replaces the basic web_scraper for procurement-type DiscoverySources.
"""
import asyncio
import io
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

logger = logging.getLogger(__name__)


# ── PDF helpers (ported from Scrapling/pdf_extractor.py) ──────────────────────

def _find_pdf_links(markdown: str) -> List[Tuple[str, str]]:
    """Return list of (display_name, url) for every PDF link in Markdown."""
    pattern = r'\[([^\]]+\.pdf[^\]]*)\]\(([^)]+)\)'
    return re.findall(pattern, markdown, re.IGNORECASE)


def _bytes_to_text(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes using pdfplumber, falling back to PyMuPDF."""
    text = _extract_pdfplumber(pdf_bytes)
    if not text.strip():
        text = _extract_pymupdf(pdf_bytes)
    return text.strip()


def _extract_pdfplumber(pdf_bytes: bytes) -> str:
    pages = []
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for i, page in enumerate(pdf.pages, 1):
                t = page.extract_text() or ""
                if t.strip():
                    pages.append(f"--- Page {i} ---\n{t}")
    except Exception:
        pass
    return "\n\n".join(pages)


def _extract_pymupdf(pdf_bytes: bytes) -> str:
    pages = []
    try:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        for i, page in enumerate(doc, 1):
            t = page.get_text()
            if t.strip():
                pages.append(f"--- Page {i} ---\n{t}")
        doc.close()
    except Exception:
        pass
    return "\n\n".join(pages)


# ── Main crawler class ─────────────────────────────────────────────────────────

class StealthCrawler:
    """
    Stealth browser crawler built on Scrapling's AsyncStealthySession.

    Usage (sync context via _run_async):
        crawler = StealthCrawler()
        result = _run_async(crawler.crawl_listing(url, keywords=[...]))
        await crawler.close()
    """

    HIGHERGOV_BASE = "https://www.highergov.com"

    def __init__(self, headless: bool = True, max_concurrent: int = 5):
        self.headless = headless
        self.max_concurrent = max_concurrent
        self.session = None                          # AsyncStealthySession (persistent)
        self.is_logged_in: Dict[str, bool] = {}
        self._semaphore: Optional[asyncio.Semaphore] = None

    # ── Session lifecycle ──────────────────────────────────────────────────────

    async def start_session(self):
        if self.session is None:
            from scrapling.fetchers import AsyncStealthySession
            logger.info("[StealthCrawler] Starting persistent stealth session")
            self.session = AsyncStealthySession(headless=self.headless)
            await self.session.__aenter__()
            self._semaphore = asyncio.Semaphore(self.max_concurrent)
        return self.session

    async def close(self):
        if self.session is not None:
            logger.info("[StealthCrawler] Closing stealth session")
            try:
                await self.session.__aexit__(None, None, None)
            except Exception:
                pass
            self.session = None
            self.is_logged_in = {}

    # ── Anti-bot detection ─────────────────────────────────────────────────────

    def _is_blocked(self, page) -> bool:
        title = (page.xpath("//title/text()").get() or "").strip()
        blocked_statuses = page.status in (202, 403, 503, 429)
        challenge_titles = any(kw in title for kw in [
            "Just a moment", "Robot Check", "Security Verification",
            "Attention Required", "DataDome", "Access Denied",
        ])
        return blocked_statuses or challenge_titles or not title or "Access Denied" in title

    # ── Authentication ─────────────────────────────────────────────────────────

    async def login_highergov(self, email: str, password: str) -> bool:
        """
        Authenticate against HigherGov. Skips quickly if login URL is unreachable
        so the rest of the crawl is not blocked by a 30-second timeout.
        """
        from app.config import get_settings
        import httpx
        settings = get_settings()
        domain = "highergov.com"

        if self.is_logged_in.get(domain):
            logger.debug("[StealthCrawler] Already logged in to HigherGov")
            return True

        login_url = settings.HIGHERGOV_LOGIN_URL
        if not login_url:
            logger.info("[StealthCrawler] HIGHERGOV_LOGIN_URL not set — proceeding without auth")
            return False

        # Fast pre-check: confirm the login page exists before launching browser auth
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=8) as client:
                probe = await client.get(login_url)
                if probe.status_code == 404:
                    logger.warning(
                        f"[StealthCrawler] Login URL {login_url} returned 404 — "
                        "skipping auth. Set HIGHERGOV_LOGIN_URL in .env to the correct URL."
                    )
                    return False
        except Exception:
            logger.warning("[StealthCrawler] Login URL unreachable — skipping auth")
            return False

        session = await self.start_session()

        async def _fill_and_submit(page):
            await page.wait_for_load_state("networkidle")
            # HigherGov-specific selectors (from Scrapling/auth_manifest.py)
            await page.locator('#id_username').fill(email, timeout=10000)
            await page.locator('#id_password').fill(password, timeout=10000)
            await page.wait_for_timeout(300)
            await page.locator('#sign_in_button').click(timeout=10000)
            try:
                await page.wait_for_url(
                    lambda u: "signin" not in u.lower() and "login" not in u.lower(),
                    timeout=15000,
                )
                logger.info("[StealthCrawler] HigherGov login successful")
            except Exception:
                logger.warning("[StealthCrawler] Login redirect timed out — may still be logged in")

        try:
            await session.fetch(login_url, page_action=_fill_and_submit,
                                network_idle=True, solve_cloudflare=False)
            self.is_logged_in[domain] = True
            return True
        except Exception as e:
            logger.error(f"[StealthCrawler] Login failed: {e}")
            return False

    async def _ensure_auth(self, url: str):
        """Auto-detect login redirect and re-authenticate if needed."""
        if "highergov.com" in url:
            from app.config import get_settings
            settings = get_settings()
            if settings.HIGHERGOV_EMAIL and settings.HIGHERGOV_PASSWORD:
                await self.login_highergov(settings.HIGHERGOV_EMAIL, settings.HIGHERGOV_PASSWORD)

    # ── Markdown conversion helper ─────────────────────────────────────────────

    @staticmethod
    def _to_markdown(page) -> str:
        try:
            from scrapling.core.shell import Convertor
            gen = Convertor._extract_content(page, extraction_type="markdown",
                                             main_content_only=False)
            return "".join(list(gen))
        except Exception as e:
            logger.debug(f"[StealthCrawler] Markdown conversion failed: {e}")
            return ""

    # ── Link extraction & filtering ────────────────────────────────────────────

    @staticmethod
    def _extract_links(markdown: str, base_url: str) -> List[str]:
        raw = re.findall(r'(?<!!)[\[][^\]]*[\]]\(([^)]+)\)', markdown)
        hrefs_from_attrs = re.findall(r'href=["\']([^"\']+)["\']', markdown)
        all_raw = list(set(raw + hrefs_from_attrs))
        resolved = []
        for h in all_raw:
            if h and h != "#" and not h.startswith("javascript"):
                resolved.append(urljoin(base_url, h))
        return list(set(resolved))

    @staticmethod
    def _filter_by_keywords(links: List[str], keywords: List[str]) -> List[str]:
        """
        Keep solicitation detail page links whose URL slug contains at least one keyword.

        HigherGov slugs from filtered searches are descriptive, e.g.:
          /contract-opportunity/intra-enterprise-depot-express-package-scanning-system-abc/
        Opaque FSC-code slugs (military hardware) look like:
          /contract-opportunity/41-filtering-pad-air-c-spe8e826t3076-k-7fa59/

        If no keywords provided, accept all solicitation-pattern URLs.
        """
        from urllib.parse import urlparse
        solicitation_patterns = [
            "/contract-opportunity/",
            "/award/",
            "/grant-opportunity/",
            "/contract/",
            "/solicitation/",
        ]
        # Normalise keywords for slug matching (spaces → hyphens)
        norm_kws = [kw.lower().replace(" ", "-") for kw in keywords if kw.strip()]
        plain_kws = [kw.lower() for kw in keywords if kw.strip()]

        result = []
        for link in links:
            try:
                path = urlparse(link).path.lower()
                is_solicitation = any(
                    path.startswith(pat) and len(path) > len(pat)
                    for pat in solicitation_patterns
                )
                if not is_solicitation:
                    continue
                if not norm_kws:
                    result.append(link)
                    continue
                if any(kw in path for kw in norm_kws) or any(kw in path for kw in plain_kws):
                    result.append(link)
            except Exception:
                pass
        return result

    # ── Pagination (JS-controlled, HigherGov style) ────────────────────────────

    @staticmethod
    async def _dismiss_modal_static(pw_page) -> None:
        """Dismiss any blocking modal/overlay (login wall, sign-up gate, cookie banner)."""
        try:
            # Press Escape first — works for most dismissible modals
            await pw_page.keyboard.press("Escape")
            await pw_page.wait_for_timeout(300)

            # Force-remove common modal/overlay elements via JS
            await pw_page.evaluate("""() => {
                const selectors = [
                    '#staticBackdrop',
                    '.modal.show',
                    '.modal-backdrop',
                    '[role="dialog"]',
                    '.overlay',
                    '#login-modal',
                    '#signup-modal',
                ];
                selectors.forEach(sel => {
                    document.querySelectorAll(sel).forEach(el => el.remove());
                });
                // Re-enable scrolling (modals often lock body scroll)
                document.body.style.overflow = '';
                document.body.classList.remove('modal-open');
            }""")
            await pw_page.wait_for_timeout(200)
        except Exception:
            pass  # Never let modal-dismissal crash the crawl

    async def _highergov_search(self, pw_page, keyword: str) -> str:
        """
        Type a keyword into HigherGov's search box and wait for the ?searchID= URL.
        Returns the new URL after search (e.g. ?searchID=abc123), or the original URL
        if the search input cannot be found (safe fallback — continues without filter).
        """
        original_url = pw_page.url
        logger.info(f"[StealthCrawler] === KEYWORD SEARCH START ===")
        logger.info(f"[StealthCrawler] Keyword to search: '{keyword}'")
        logger.info(f"[StealthCrawler] Current page URL before search: {original_url}")

        # Multiple selector candidates for HigherGov's keyword input.
        # Priority order: most specific first.
        # From page inspection: the Keywords filter panel input has no id/placeholder,
        # but the top "Search by Name or ID" bar (id=autoComplete) is always visible.
        # We try the dedicated keyword filter input first, then fall back to the top bar.
        input_selectors = [
            'input[placeholder*="keyword" i]',         # dedicated keyword filter if visible
            '#keyword_app input',                       # Vue multiselect keyword component
            'input[name*="keyword" i]',
            '#autoComplete',                            # top "Search by Name or ID" bar (always visible)
            'input[placeholder*="Search by Name" i]',
        ]

        # Log all visible inputs on the page for debugging
        try:
            all_inputs = await pw_page.evaluate("""() => {
                return [...document.querySelectorAll('input')].map(el => ({
                    type: el.type,
                    name: el.name,
                    placeholder: el.placeholder,
                    id: el.id,
                    class: el.className.substring(0, 80),
                    visible: el.offsetParent !== null
                }));
            }""")
            logger.info(f"[StealthCrawler] Inputs found on page: {all_inputs}")
        except Exception as e:
            logger.debug(f"[StealthCrawler] Could not enumerate inputs: {e}")

        search_input = None
        for sel in input_selectors:
            try:
                loc = pw_page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    search_input = loc
                    logger.info(f"[StealthCrawler] ✓ Search input found with selector: '{sel}'")
                    break
                else:
                    logger.debug(f"[StealthCrawler] Selector '{sel}' — not found or not visible")
            except Exception:
                continue

        if search_input is None:
            logger.warning(
                "[StealthCrawler] ✗ Could not find HigherGov keyword search input — "
                "proceeding without keyword filter (all solicitations will be scraped)"
            )
            return original_url

        try:
            # Clear any existing text and type the keyword
            # Note: triple_click is not available on Scrapling's locator wrapper,
            # so we use fill("") to clear then type() to enter the keyword
            await search_input.click()
            await search_input.fill(keyword)  # fill clears existing text and sets value

            # Verify what was typed
            typed_val = await search_input.input_value()
            logger.info(f"[StealthCrawler] Value typed into search box: '{typed_val}'")

            # Submit: try Enter key first, then look for a search/submit button
            submitted = False
            try:
                await search_input.press("Enter")
                submitted = True
                logger.info("[StealthCrawler] Search submitted via Enter key")
            except Exception:
                pass

            if not submitted:
                for btn_sel in ['button[type="submit"]', 'button:has-text("Search")', '[aria-label*="search" i]']:
                    try:
                        btn = pw_page.locator(btn_sel).first
                        if await btn.count() > 0 and await btn.is_visible():
                            await btn.click()
                            submitted = True
                            logger.info(f"[StealthCrawler] Search submitted via button: '{btn_sel}'")
                            break
                    except Exception:
                        continue

            if not submitted:
                logger.warning("[StealthCrawler] ✗ Could not submit search — proceeding with unfiltered results")
                return original_url

            # Wait for HigherGov to navigate to the ?searchID= URL
            logger.info("[StealthCrawler] Waiting for HigherGov search redirect...")
            await pw_page.wait_for_load_state("networkidle")
            await pw_page.wait_for_timeout(1500)  # extra settle time for JS redirect

            new_url = pw_page.url
            if "searchID" in new_url:
                # Extract the searchID and apply it to the contract-opportunity page.
                # The global autoComplete bar redirects to /all/?searchID=xxx but we
                # need /contract-opportunity/?searchID=xxx for contract-specific results.
                from urllib.parse import urlparse as _up, parse_qs as _pqs, urlencode as _ue
                parsed = _up(new_url)
                qs = _pqs(parsed.query)
                search_id = qs.get("searchID", [None])[0]

                if search_id and "/all/" in new_url:
                    contract_url = f"https://www.highergov.com/contract-opportunity/?searchID={search_id}"
                    logger.info(
                        f"[StealthCrawler] Global search redirected to /all/ — "
                        f"re-navigating to contract-opportunity page: {contract_url}"
                    )
                    await pw_page.goto(contract_url, wait_until="networkidle")
                    await pw_page.wait_for_timeout(1000)
                    final_url = pw_page.url
                    logger.info(f"[StealthCrawler] ✓ Contract-opportunity filtered URL: {final_url}")
                    logger.info(f"[StealthCrawler] === KEYWORD SEARCH END ===")
                    return final_url
                else:
                    logger.info(f"[StealthCrawler] ✓ Search redirect confirmed — searchID URL: {new_url}")
            elif new_url != original_url:
                logger.info(f"[StealthCrawler] ✓ URL changed after search: {new_url}")
            else:
                logger.warning(
                    f"[StealthCrawler] ✗ URL did NOT change after search (still: {new_url}) — "
                    "results may be unfiltered"
                )

            logger.info(f"[StealthCrawler] === KEYWORD SEARCH END ===")
            return new_url

        except Exception as e:
            logger.warning(f"[StealthCrawler] ✗ HigherGov search interaction failed: {e} — proceeding without filter")
            return original_url

    async def _apply_active_filter(self, pw_page) -> bool:
        """
        Best-effort: activate HigherGov's 'Active' bid status filter so only
        open solicitations (deadline not yet passed) appear in results.

        Uses JavaScript to interact with the Vue.js filter state directly,
        which is more reliable than clicking hidden DOM elements.
        Returns True if applied, False if not (safe — caller continues either way).
        The existing _is_deadline_future() gate in CaptureService is the hard safety net.
        """
        try:
            # Ask the page what filter-related Vue data it has
            filter_info = await pw_page.evaluate("""() => {
                // Look for Vue instances that hold filter state
                const inputs = [...document.querySelectorAll('input, select')].map(el => ({
                    id: el.id, name: el.name, type: el.type,
                    placeholder: el.placeholder, value: el.value
                }));
                // Look for any visible filter buttons or chips mentioning 'Active'
                const activeEls = [...document.querySelectorAll('*')]
                    .filter(el => el.children.length === 0
                        && el.innerText
                        && el.innerText.trim() === 'Active'
                        && el.offsetParent !== null)
                    .map(el => ({ tag: el.tagName, class: el.className, id: el.id }));
                return { activeEls };
            }""")
            logger.info(f"[StealthCrawler] Active filter search — visible 'Active' elements: {filter_info.get('activeEls', [])}")

            # Strategy 1: click a visible element with text "Active" in a filter context
            active_locators = [
                pw_page.get_by_role("option", name="Active"),
                pw_page.get_by_role("checkbox", name=re.compile("active", re.I)),
                pw_page.locator('.badge:has-text("Active")'),
                pw_page.locator('[class*="filter"]:has-text("Active")'),
                pw_page.locator('label:has-text("Active")'),
            ]
            for loc in active_locators:
                try:
                    if await loc.count() > 0 and await loc.first.is_visible():
                        await loc.first.click()
                        await pw_page.wait_for_load_state("networkidle")
                        logger.info("[StealthCrawler] ✓ Active bid status filter applied via element click")
                        return True
                except Exception:
                    continue

            # Strategy 2: set the response-deadline date filter via JavaScript
            # HigherGov uses 'date2.relative_after' for "deadline N+ days from now"
            # Setting it to 0 means "deadline today or later" = active solicitations
            result = await pw_page.evaluate("""() => {
                const el = document.getElementById('date2.relative_after');
                if (el) {
                    el.value = '0';
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    return true;
                }
                return false;
            }""")
            if result:
                await pw_page.wait_for_timeout(1500)
                await pw_page.wait_for_load_state("networkidle")
                logger.info("[StealthCrawler] ✓ Response deadline filter set to today+ via JavaScript")
                return True

            logger.info(
                "[StealthCrawler] Active filter not applied — no matching filter element found. "
                "Expired solicitations will be caught by the deadline gate in CaptureService."
            )
            return False

        except Exception as e:
            logger.debug(f"[StealthCrawler] Active filter attempt failed: {e} — continuing without it")
            return False

    async def _collect_all_links_paginated(self, listing_url: str, search_keyword: str = "") -> List[str]:
        """
        Handles HigherGov's JavaScript-controlled pagination.
        Strategy: open live Playwright tab, detect total pages, intercept the
        XHR/fetch API call, replay it for all remaining pages in parallel.
        Falls back to click-through if no API endpoint is found.
        """
        import httpx

        session = await self.start_session()
        all_links: List[str] = []

        pw_page = await session.context.new_page()
        try:
            captured_api: Dict[str, Any] = {"requests": []}

            async def on_request(req):
                rt = req.resource_type
                url_l = req.url.lower()
                if rt in ("xhr", "fetch") and not any(
                    x in url_l for x in ("analytics", "tracking", "beacon", "font", "css", "static")
                ):
                    captured_api["requests"].append({
                        "url": req.url,
                        "method": req.method,
                        "headers": dict(req.headers),
                        "post_data": req.post_data,
                    })

            pw_page.on("request", on_request)
            logger.info(f"[StealthCrawler] Opening listing page: {listing_url}")
            await pw_page.goto(listing_url, wait_until="networkidle")

            # If a search keyword is provided and this is HigherGov, type it into the
            # search box so HigherGov generates a ?searchID= filtered URL.
            # This is the only reliable way to filter — ?q= in the URL is ignored by HigherGov.
            if search_keyword and "highergov.com" in listing_url:
                await self._dismiss_modal_static(pw_page)
                listing_url = await self._highergov_search(pw_page, search_keyword)
                # Best-effort: apply Active/Open status filter to exclude expired solicitations.
                # Falls through safely if not found — CaptureService._is_deadline_future() is the hard gate.
                await self._apply_active_filter(pw_page)
                logger.info(f"[StealthCrawler] Collecting links from filtered URL: {listing_url}")

            # Detect total page count from visible pagination buttons
            total_pages = await pw_page.evaluate("""() => {
                const texts = [...document.querySelectorAll('ul a, ol a, li a, button')]
                    .map(el => el.innerText.trim())
                    .filter(t => /^\\d+$/.test(t))
                    .map(Number);
                return texts.length ? Math.max(...texts) : 1;
            }""")
            logger.info(f"[StealthCrawler] Pagination: {total_pages} page(s) detected")

            def _hrefs_from_html(html: str) -> List[str]:
                raw = re.findall(r'href=["\']([^"\']+)["\']', html)
                return [urljoin(listing_url, h) for h in raw
                        if h and h != "#" and not h.startswith("javascript")]

            # Page 1 links
            page1_html = await pw_page.content()
            all_links.extend(_hrefs_from_html(page1_html))
            logger.debug(f"[StealthCrawler] Page 1: {len(all_links)} links")

            if total_pages <= 1:
                return list(set(all_links))

            # Click page 2 to capture the XHR/API call
            captured_api["requests"] = []
            page2_btn = pw_page.locator('ul a, ol a, li a').filter(
                has_text=re.compile(r'^\s*2\s*$')
            ).first
            if await page2_btn.count() == 0:
                page2_btn = pw_page.get_by_role("link", name="2").first

            api_base_url = None
            api_params_template = None

            # Dismiss any login-wall / sign-up modal that blocks clicks
            await self._dismiss_modal_static(pw_page)

            if await page2_btn.count() > 0 and await page2_btn.is_visible():
                await page2_btn.click()
                await pw_page.wait_for_load_state("networkidle")
                await pw_page.wait_for_timeout(800)

                for req in captured_api["requests"]:
                    # GET-style pagination (?page=N, ?offset=N, etc.)
                    if re.search(r'[?&](page|offset|cursor|p|start)=', req["url"], re.I):
                        api_base_url = re.sub(
                            r'([?&])(page|offset|cursor|p|start)=\w+', '', req["url"], flags=re.I
                        ).rstrip("?&")
                        api_params_template = req
                        logger.info(f"[StealthCrawler] API endpoint found: {api_base_url}")
                        break
                    # DataTables POST-style (draw/length/start in POST body)
                    if req["method"] == "POST" and req.get("post_data") and \
                       re.search(r'(draw|length|start)=', req.get("post_data", ""), re.I):
                        api_base_url = req["url"]
                        api_params_template = req
                        logger.info(f"[StealthCrawler] DataTables API found: {api_base_url}")
                        logger.debug(f"[StealthCrawler] DataTables POST body: {req.get('post_data', '')[:500]}")
                        break

                page2_html = await pw_page.content()
                all_links.extend(_hrefs_from_html(page2_html))

            # Strategy A: replay API calls in parallel for remaining pages.
            # When ?q= is present, the browser JS sets the DataTables search state before
            # clicking page 2 — so the captured POST body already includes the search filter.
            # We use that same POST body for all subsequent pages (just changing start= offset).
            if api_base_url and api_params_template:
                cookies = {c["name"]: c["value"] for c in await session.context.cookies()}
                headers = {k: v for k, v in api_params_template["headers"].items()
                           if k.lower() not in ("content-length",)}
                is_post = api_params_template.get("method", "GET").upper() == "POST"
                post_body_template = api_params_template.get("post_data", "") or ""

                # Detect page size from DataTables POST body (length=N) or default 25
                page_size = 25
                if is_post:
                    m = re.search(r'length=(\d+)', post_body_template)
                    if m:
                        page_size = int(m.group(1))

                async def _fetch_api_page(pg: int) -> List[str]:
                    async with httpx.AsyncClient(cookies=cookies, headers=headers,
                                                  follow_redirects=True, timeout=30) as client:
                        if is_post:
                            # DataTables: replace start= offset in POST body
                            start_offset = (pg - 1) * page_size
                            body = re.sub(r'draw=\d+', f'draw={pg}', post_body_template)
                            body = re.sub(r'start=\d+', f'start={start_offset}', body)
                            resp = await client.post(api_base_url, content=body,
                                                     headers={**headers, "Content-Type": "application/x-www-form-urlencoded"})
                        else:
                            sep = "&" if "?" in api_base_url else "?"
                            resp = await client.get(f"{api_base_url}{sep}page={pg}")

                        if resp.status_code != 200:
                            return []
                        text = resp.text
                        # DataTables JSON: extract "url" fields or href patterns
                        hrefs = re.findall(r'"url"\s*:\s*"([^"]+)"', text)
                        if not hrefs:
                            hrefs = re.findall(r'href=["\']([^"\']+)["\']', text)
                        return [urljoin(listing_url, h) for h in hrefs
                                if h and h != "#" and not h.startswith("javascript")]

                pages_to_fetch = list(range(3, total_pages + 1))
                logger.info(
                    f"[StealthCrawler] Fetching pages 3-{total_pages} via "
                    f"{'DataTables POST' if is_post else 'GET'} API"
                )
                results = await asyncio.gather(*[_fetch_api_page(p) for p in pages_to_fetch])
                for r in results:
                    all_links.extend(r)

            else:
                # Strategy B: sequential click-through — capped at MAX_CLICK_PAGES
                MAX_CLICK_PAGES = 5
                page_limit = min(total_pages, MAX_CLICK_PAGES + 2)  # +2 because pages 1&2 already done
                logger.info(
                    f"[StealthCrawler] No API found — clicking pages 3-{page_limit} "
                    f"(capped from {total_pages} to avoid timeout)"
                )
                for pg in range(3, page_limit + 1):
                    try:
                        await self._dismiss_modal_static(pw_page)
                        btn = pw_page.locator('ul a, ol a, li a').filter(
                            has_text=re.compile(rf'^\s*{pg}\s*$')
                        ).first
                        if await btn.count() == 0:
                            btn = pw_page.get_by_role("link", name=str(pg)).first
                        if await btn.count() > 0 and await btn.is_visible():
                            await btn.click()
                            await pw_page.wait_for_load_state("networkidle")
                            await pw_page.wait_for_timeout(500)
                            html = await pw_page.content()
                            new_links = _hrefs_from_html(html)
                            all_links.extend(new_links)
                            logger.info(
                                f"[StealthCrawler] Page {pg}/{page_limit}: "
                                f"+{len(new_links)} links (total so far: {len(all_links)})"
                            )
                        else:
                            logger.warning(f"[StealthCrawler] Page {pg} button not found — stopping pagination")
                            break
                    except Exception as e:
                        logger.warning(f"[StealthCrawler] Page {pg} click failed: {e} — skipping")

        finally:
            await pw_page.close()

        # Deduplicate preserving order
        seen: set = set()
        deduped = []
        for link in all_links:
            if link not in seen:
                seen.add(link)
                deduped.append(link)
        return deduped

    # ── PDF extraction ────────────────────────────────────────────────────────

    async def _fetch_pdf_bytes(self, doc_url: str, retries: int = 2) -> Optional[bytes]:
        """Download a PDF from a URL or document detail page, with retry."""
        session = await self.start_session()
        full_url = doc_url if doc_url.startswith("http") else self.HIGHERGOV_BASE + doc_url

        for attempt in range(1, retries + 1):
            try:
                result = await self._fetch_pdf_bytes_core(session, full_url)
                if result:
                    return result
            except Exception as e:
                logger.debug(f"[StealthCrawler] PDF attempt {attempt} failed for {doc_url}: {e}")
                if attempt < retries:
                    await asyncio.sleep(2)
        return None

    async def _fetch_pdf_bytes_core(self, session, full_url: str) -> Optional[bytes]:
        """Core PDF download logic — intercept network responses or click download button."""
        pw_page = await session.context.new_page()
        try:
            pdf_holder: List[bytes] = []

            async def capture_response(response):
                ct = response.headers.get("content-type", "")
                cd = response.headers.get("content-disposition", "")
                url_l = response.url.lower()
                if "pdf" in ct or "pdf" in cd.lower() or url_l.endswith(".pdf"):
                    try:
                        body = await response.body()
                        if body[:4] == b"%PDF":
                            pdf_holder.append(body)
                    except Exception:
                        pass

            pw_page.on("response", capture_response)

            # Fast path: direct .pdf URL
            if full_url.lower().endswith(".pdf"):
                await pw_page.goto(full_url, wait_until="networkidle", timeout=60000)
                return pdf_holder[0] if pdf_holder else None

            # Slow path: document detail page — navigate then click download
            await pw_page.goto(full_url, wait_until="networkidle", timeout=60000)
            if pdf_holder:
                return pdf_holder[0]

            download_selectors = [
                'a[href$=".pdf"]',
                'a[href*="/download"]',
                'a:has-text("Download")',
                'button:has-text("Download")',
                'a[download]',
            ]
            for sel in download_selectors:
                try:
                    elem = pw_page.locator(sel).first
                    if not await elem.is_visible():
                        continue
                    href = await elem.get_attribute("href") or ""
                    if href.endswith(".pdf"):
                        target = href if href.startswith("http") else self.HIGHERGOV_BASE + href
                        await pw_page.goto(target, wait_until="networkidle", timeout=60000)
                        return pdf_holder[0] if pdf_holder else None
                    await elem.click()
                    await pw_page.wait_for_timeout(4000)
                    if pdf_holder:
                        return pdf_holder[0]
                    break
                except Exception:
                    continue

            return pdf_holder[0] if pdf_holder else None
        finally:
            await pw_page.close()

    async def _extract_pdfs_from_markdown(
        self, markdown: str, max_concurrent: int = 3, base_url: str = ""
    ) -> Dict[str, Dict]:
        """
        Find PDF links in markdown, download + extract text for each.
        Returns: { display_name: { "url": str, "text": str } }
        """
        links = _find_pdf_links(markdown)
        if not links:
            return {}
        # Resolve relative URLs so stored attachment_urls are always absolute
        if base_url:
            links = [(name, urljoin(base_url, url)) for name, url in links]

        logger.info(f"[StealthCrawler] Found {len(links)} PDF link(s) to extract")
        sem = asyncio.Semaphore(max_concurrent)

        async def _process(display_name: str, doc_url: str) -> Tuple[str, Dict]:
            async with sem:
                try:
                    pdf_bytes = await self._fetch_pdf_bytes(doc_url)
                    if not pdf_bytes:
                        return display_name, {"url": doc_url, "text": "[ERROR] Could not retrieve PDF bytes"}
                    text = _bytes_to_text(pdf_bytes)
                    return display_name, {"url": doc_url, "text": text if text else "[EMPTY] No text extracted"}
                except Exception as e:
                    return display_name, {"url": doc_url, "text": f"[ERROR] {e}"}

        tasks = [_process(name, url) for name, url in links]
        results = await asyncio.gather(*tasks)
        return dict(results)

    # ── Single page scrape ─────────────────────────────────────────────────────

    async def _scrape_single(self, url: str) -> Dict[str, Any]:
        """
        Scrape one URL with stealth session.
        Returns: { url, status, markdown, pdf_contents }
        """
        async with self._semaphore:
            start = time.time()
            session = await self.start_session()
            try:
                logger.debug(f"[StealthCrawler] Scraping: {url}")
                page = await session.fetch(url, solve_cloudflare=False, network_idle=True)

                # Auto-auth: if bounced to login page
                current = page.url.lower()
                if "login" in current or "signin" in current:
                    await self._ensure_auth(url)
                    page = await session.fetch(url, solve_cloudflare=False, network_idle=True)

                if self._is_blocked(page):
                    logger.debug(f"[StealthCrawler] Block detected on {url}, retrying with solver")
                    page = await session.fetch(url, solve_cloudflare=True, network_idle=False)

                markdown = self._to_markdown(page)
                pdf_contents = await self._extract_pdfs_from_markdown(markdown, base_url=url)

                return {
                    "url":          url,
                    "status":       page.status,
                    "markdown":     markdown,
                    "pdf_contents": pdf_contents,
                    "elapsed":      round(time.time() - start, 2),
                }
            except Exception as e:
                logger.warning(f"[StealthCrawler] Scrape failed for {url}: {e}")
                return {
                    "url": url, "status": 0, "markdown": "",
                    "pdf_contents": {}, "elapsed": 0, "error": str(e),
                }

    # ── Public: crawl a procurement listing ───────────────────────────────────

    async def crawl_listing(
        self,
        listing_url: str,
        keywords: List[str],
        authenticated: bool = True,
    ) -> Dict[str, Any]:
        """
        Full pipeline for a procurement listing page:
        1. Authenticate (if credentials configured)
        2. Collect all solicitation links across all pages (handles JS pagination)
        3. Filter links by keyword
        4. Parallel scrape of each matching link + PDF extraction

        Returns:
            {
                listing_url, total_links, filtered_links,
                sub_results: [{ url, status, markdown, pdf_contents }]
            }
        """
        await self.start_session()
        self._semaphore = asyncio.Semaphore(self.max_concurrent)

        # Step 1: Authenticate
        if authenticated:
            await self._ensure_auth(listing_url)

        # Step 2: Collect all links across pages.
        # Pass the first keyword so the browser types it into HigherGov's search box,
        # generating a real ?searchID= filtered URL — the only reliable filter on HigherGov.
        search_keyword = keywords[0] if keywords else ""
        logger.info(f"[StealthCrawler] Collecting links from: {listing_url} (keyword: '{search_keyword}')")
        all_links = await self._collect_all_links_paginated(listing_url, search_keyword=search_keyword)
        logger.info(f"[StealthCrawler] Total unique links found: {len(all_links)}")

        # Step 3: Accept all /contract-opportunity/ URLs — HigherGov's search already filtered
        # the results to the keyword via the ?searchID= URL. Slug-based keyword matching is
        # unreliable because HigherGov slugs are opaque FSC codes, not readable text.
        filtered = self._filter_by_keywords(all_links, [])  # [] = accept all solicitation-pattern URLs
        logger.info(
            f"[StealthCrawler] Solicitation links accepted: {len(filtered)} / {len(all_links)}"
        )

        # Step 4: Scrape each solicitation sequentially (respects semaphore, avoids mass timeout)
        # Cap at 40 URLs to keep scan time under ~80 min; page-1 results (most relevant) come first
        MAX_TO_SCRAPE = 40
        if len(filtered) > MAX_TO_SCRAPE:
            logger.info(
                f"[StealthCrawler] Capping scrape at {MAX_TO_SCRAPE} URLs "
                f"(skipping {len(filtered) - MAX_TO_SCRAPE} lower-priority links)"
            )
            filtered = filtered[:MAX_TO_SCRAPE]

        sub_results = []
        for i, url in enumerate(filtered):
            logger.info(f"[StealthCrawler] Scraping {i+1}/{len(filtered)}: {url}")
            try:
                result = await asyncio.wait_for(self._scrape_single(url), timeout=120)
                sub_results.append(result)
            except asyncio.TimeoutError:
                logger.warning(f"[StealthCrawler] Timeout scraping {url} — skipped")
                sub_results.append({"url": url, "status": "timeout", "markdown": "", "pdf_contents": {}})

        return {
            "listing_url":    listing_url,
            "total_links":    len(all_links),
            "filtered_links": filtered,
            "sub_results":    sub_results,
        }

    async def scrape_url(self, url: str) -> Dict[str, Any]:
        """
        Scrape a single solicitation URL (for manual one-off scans from UI).
        Returns: { url, status, markdown, pdf_contents }
        """
        await self.start_session()
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrent)
        await self._ensure_auth(url)
        return await self._scrape_single(url)


# ── Dedicated background event loop for Playwright ────────────────────────────
# Playwright's BrowserContext is bound to the event loop it was created in.
# FastAPI runs its own event loop, so we must keep all crawler coroutines on a
# single dedicated background loop — never mix loops.

import threading as _threading

_bg_loop: Optional[asyncio.AbstractEventLoop] = None
_bg_thread: Optional[_threading.Thread] = None
_bg_lock = _threading.Lock()


def _get_bg_loop() -> asyncio.AbstractEventLoop:
    """Return (and lazily start) the persistent background event loop."""
    global _bg_loop, _bg_thread
    with _bg_lock:
        if _bg_loop is None or _bg_loop.is_closed():
            _bg_loop = asyncio.new_event_loop()
            _bg_thread = _threading.Thread(
                target=_bg_loop.run_forever, daemon=True, name="crawler-bg-loop"
            )
            _bg_thread.start()
            logger.info("[StealthCrawler] Background event loop started")
    return _bg_loop


def run_async(coro):
    """
    Run an async coroutine from any context (sync or async).

    When called from FastAPI's async context (loop already running), we dispatch
    to the dedicated crawler background loop so Playwright's BrowserContext is
    always created and used in the same loop — avoiding the 'future belongs to a
    different loop' error.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Dispatch to the persistent background loop
            bg_loop = _get_bg_loop()
            future = asyncio.run_coroutine_threadsafe(coro, bg_loop)
            return future.result(timeout=600)  # 10-minute hard cap
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


# ── Singleton ──────────────────────────────────────────────────────────────────

_crawler: Optional[StealthCrawler] = None


def get_stealth_crawler() -> StealthCrawler:
    global _crawler
    if _crawler is None:
        from app.config import get_settings
        settings = get_settings()
        _crawler = StealthCrawler(
            headless=True,
            max_concurrent=settings.CAPTURE_MAX_CONCURRENT,
        )
    return _crawler
