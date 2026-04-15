"""
Lead Discovery Agent — periodically scrapes configured sources and auto-creates Signals.

Routing logic:
- source_type == "procurement"  → CaptureService (Scrapling stealth + 10-section extraction)
- source_type == "job_board" | "news"  → existing web_scraper / snippet → Signal pipeline

The cold email pipeline and Signal/Opportunity models are NOT affected.
"""
import asyncio
import logging
import json
from datetime import datetime
from typing import List

from app.utils.text_cleaner import clean_html_text

logger = logging.getLogger(__name__)

MIN_CONFIDENCE = 0.6  # only save signals with confidence above this threshold


def _run_async(coro):
    """Run an async coroutine from a sync context safely."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


class LeadDiscoveryAgent:
    """
    Scrapes configured sources and feeds discovered leads into the pipeline.

    - procurement sources → CaptureService → Solicitation records
    - job_board / news sources → snippet classifier → Signal + Opportunity records
    """

    def run_all_sources(self):
        """Scan all active discovery sources + run global search. Called by APScheduler."""
        from app.database import SessionLocal
        from app.models import DiscoverySource

        db = SessionLocal()
        try:
            sources = db.query(DiscoverySource).filter(DiscoverySource.is_active == True).all()
            logger.info(f"[Discovery] Running scan for {len(sources)} active source(s)")
            for source in sources:
                try:
                    self.scan_source(source, db)
                    source.last_scanned_at = datetime.utcnow()
                    db.commit()
                except Exception as e:
                    logger.error(f"[Discovery] Source '{source.name}' scan failed: {e}")
        finally:
            db.close()

        # Also run global SearXNG search alongside configured sources
        try:
            self.run_global_search()
        except Exception as e:
            logger.error(f"[Discovery] Global search failed: {e}")

    def run_global_search(self):
        """Search via SearXNG (web_scraper module) with configured keywords and process results as signals."""
        from app.config import get_settings
        from app.database import SessionLocal

        settings = get_settings()
        if not settings.SEARCH_ENABLED:
            logger.info("[Search] Global search is disabled (SEARCH_ENABLED=False)")
            return

        keywords = self._get_active_keywords()
        if not keywords:
            logger.info("[Search] No active keyword set configured, skipping")
            return

        try:
            from web_scraper import WebScraper
        except ImportError:
            logger.warning("[Search] web_scraper module not found — ensure web_scraper/ is in project root")
            return

        logger.info(f"[Search] Running SearXNG search for {len(keywords)} keyword(s)")

        db = SessionLocal()
        signals_created = 0
        try:
            for query in keywords:
                try:
                    scraper = WebScraper()
                    output = _run_async(scraper.search_and_scrape(query, max_urls=5))
                    for crawl_result in output.successful():
                        # Combine title from metadata + first 500 chars of content as snippet
                        title = crawl_result.metadata.get("title", "")
                        body = crawl_result.content[:500] if crawl_result.content else ""
                        snippet = f"{title}. {body}".strip()
                        if len(snippet) > 60:
                            created = self._process_snippet(snippet, crawl_result.url, db)
                            if created:
                                signals_created += 1
                except Exception as e:
                    logger.warning(f"[Search] Query '{query}' failed: {e}")
        finally:
            db.close()

        logger.info(f"[Search] Global search created {signals_created} new signal(s)")

    def _get_active_keywords(self) -> List[str]:
        from app.database import SessionLocal
        from app.core.keywords import normalize_keywords
        from app.models import KeywordSet

        db = SessionLocal()
        try:
            active = db.query(KeywordSet).filter(KeywordSet.is_active == True).first()
            if not active or not active.keywords:
                return []
            return normalize_keywords(json.loads(active.keywords))
        except Exception as e:
            logger.warning(f"[Search] Could not load active keyword set: {e}")
            return []
        finally:
            db.close()

    def scan_source(self, source, db) -> int:
        """
        Route a single source to the correct pipeline based on source_type.

        - "procurement" → CaptureService (Scrapling + 10-section LLM extraction → Solicitation)
        - "job_board" | "news" → existing snippet→Signal pipeline (unchanged)

        Returns:
            Number of new records created (Solicitation or Signal)
        """
        if source.source_type == "procurement":
            return self._scan_procurement(source, db)
        else:
            return self._scan_basic(source, db)

    def _scan_procurement(self, source, db) -> int:
        """
        Procurement source: full Scrapling-based capture pipeline.
        Delegates entirely to CaptureService — creates Solicitation records.
        """
        logger.info(f"[Discovery] Procurement scan: {source.name} ({source.url})")
        try:
            from app.services.capture_service import get_capture_service
            return get_capture_service().scan_source(source, db)
        except Exception as e:
            logger.error(f"[Discovery] Procurement scan failed for {source.name}: {e}")
            return 0

    def _scan_basic(self, source, db) -> int:
        """
        Job board / news source: scrape → extract snippets → classify → Signal + Opportunity.
        This is the original scan_source logic, preserved unchanged.
        """
        logger.info(f"[Discovery] Basic scan: {source.name} ({source.url})")

        keywords: List[str] = []
        if source.keywords:
            try:
                keywords = json.loads(source.keywords)
            except Exception:
                keywords = []

        raw_text = self._scrape(source.url)
        if not raw_text:
            logger.warning(f"[Discovery] No text scraped from {source.url}")
            return 0

        snippets = self._extract_relevant_snippets(raw_text, keywords)
        logger.info(f"[Discovery] Found {len(snippets)} relevant snippet(s) in {source.name}")

        signals_created = 0
        for snippet in snippets[:10]:
            created = self._process_snippet(snippet, source.url, db)
            if created:
                signals_created += 1

        logger.info(f"[Discovery] Created {signals_created} new signal(s) from {source.name}")
        return signals_created

    def _scrape(self, url: str) -> str:
        """Scrape and clean text from a URL using web_scraper module (basic, non-stealth)."""
        try:
            from web_scraper.crawler import Crawler
            result = _run_async(Crawler().crawl(url))
            if result.success and result.content:
                return clean_html_text(result.content)
            logger.debug(f"[Scrape] web_scraper returned no content for {url}: {result.error}")
            return ""
        except ImportError:
            import requests
            from bs4 import BeautifulSoup
            try:
                resp = requests.get(url, timeout=15)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.content, "html.parser")
                for tag in soup(["script", "style", "nav", "footer"]):
                    tag.decompose()
                return clean_html_text(soup.get_text())
            except Exception as e:
                logger.debug(f"Fallback scrape failed for {url}: {e}")
                return ""
        except Exception as e:
            logger.debug(f"Scrape failed for {url}: {e}")
            return ""

    def _extract_relevant_snippets(self, text: str, keywords: List[str]) -> List[str]:
        """Split text into paragraphs and return those containing any keyword."""
        if not keywords:
            # No keywords configured — return first few paragraphs
            paras = [p.strip() for p in text.split("\n") if len(p.strip()) > 80]
            return paras[:5]

        lower_keywords = [k.lower() for k in keywords]
        paras = [p.strip() for p in text.split("\n") if len(p.strip()) > 60]

        matching = []
        for para in paras:
            lower_para = para.lower()
            if any(kw in lower_para for kw in lower_keywords):
                matching.append(para)

        return matching

    def _process_snippet(self, snippet: str, source_url: str, db) -> bool:
        """
        Classify a snippet and save as a Signal + Opportunity if relevant.

        Returns:
            True if a new Signal was created
        """
        try:
            from app.services.signal_classifier import get_signal_classifier
            from app.models import Signal, Opportunity
            import json

            classifier = get_signal_classifier()
            result = classifier.classify(snippet, source_url=source_url)

            if result.signal_type == "other" or result.confidence_score < MIN_CONFIDENCE:
                return False

            # Avoid duplicates within a 7-day window
            from datetime import timedelta
            cutoff = datetime.utcnow() - timedelta(days=7)

            if result.company_name:
                # Deduplicate by company name + signal type
                existing = (
                    db.query(Signal)
                    .filter(
                        Signal.company_name == result.company_name,
                        Signal.signal_type == result.signal_type,
                        Signal.created_at >= cutoff,
                    )
                    .first()
                )
                if existing:
                    logger.debug(
                        f"[Discovery] Skipping duplicate signal for {result.company_name}"
                    )
                    return False
            else:
                # No company name (e.g. government RFPs) — deduplicate by source URL + type
                existing = (
                    db.query(Signal)
                    .filter(
                        Signal.source_url == source_url,
                        Signal.signal_type == result.signal_type,
                        Signal.created_at >= cutoff,
                    )
                    .first()
                )
                if existing:
                    logger.debug(
                        f"[Discovery] Skipping duplicate signal for URL {source_url}"
                    )
                    return False

            # Save Signal
            signal = Signal(
                source_url=source_url,
                raw_text=snippet[:2000],
                signal_type=result.signal_type,
                company_name=result.company_name,
                detected_skills=json.dumps(result.detected_skills),
                confidence_score=result.confidence_score,
                status="new",
            )
            db.add(signal)
            db.flush()  # get signal.id without committing yet

            # Score and create Opportunity
            from app.services.opportunity_scorer import get_opportunity_scorer
            scorer = get_opportunity_scorer()
            scores = scorer.score_from_skills(result.detected_skills)
            skill_match = scores["skill_match_score"]
            overall = scorer.compute_overall(skill_match, result.confidence_score)
            priority = scorer.compute_priority(overall)
            opp_type = "email_outreach" if result.signal_type == "job_hiring" else "proposal"

            opportunity = Opportunity(
                signal_id=signal.id,
                company_name=result.company_name,
                source_url=source_url,
                opportunity_type=opp_type,
                skill_match_score=skill_match,
                signal_strength=result.confidence_score,
                overall_score=overall,
                priority=priority,
                status="new",
            )
            db.add(opportunity)
            db.commit()

            # Notify for proposal-type signals
            if result.signal_type in ("rfp_opportunity", "service_request"):
                try:
                    from app.services.notification_service import get_notification_service
                    get_notification_service().notify_opportunity(opportunity, result, db)
                except Exception as notif_err:
                    logger.warning(f"Notification failed: {notif_err}")

            logger.info(
                f"[Discovery] New signal: {result.signal_type} | {result.company_name} "
                f"| confidence={result.confidence_score:.2f} | priority={priority}"
            )
            return True

        except Exception as e:
            logger.error(f"[Discovery] Failed to process snippet: {e}")
            db.rollback()
            return False


# Singleton
_agent = None


def get_lead_discovery_agent() -> LeadDiscoveryAgent:
    global _agent
    if _agent is None:
        _agent = LeadDiscoveryAgent()
    return _agent
