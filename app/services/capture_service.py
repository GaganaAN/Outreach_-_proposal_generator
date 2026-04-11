"""
CaptureService — orchestrates the full Capture Management pipeline:

1. StealthCrawler  → fetch solicitation URLs from procurement listing (e.g. HigherGov)
2. PDF extraction  → download and extract attached documents per solicitation page
3. LLM extraction  → run CAPTURE_QUALIFICATION_PROMPT → all 10 PRD sections
4. Deduplication   → skip URLs already seen within 30 days
5. DB persistence  → save Solicitation records + send email notification
6. Scope scoring   → normalise scope_match_percentage → scope_match_score (0-1)

This service is called by LeadDiscoveryAgent for procurement-type sources,
and also directly from capture_routes.py for manual scans.
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Minimum scope match percentage to save a solicitation
MIN_SCOPE_MATCH_PCT = 20


class CaptureService:

    def __init__(self):
        from app.config import get_settings
        self.settings = get_settings()

    # ── Public: scan a procurement DiscoverySource ─────────────────────────────

    def scan_source(self, source, db) -> int:
        """
        Scan a DiscoverySource of type 'procurement' using StealthCrawler.

        Args:
            source: DiscoverySource ORM instance
            db:     Active SQLAlchemy session

        Returns:
            Number of new Solicitation records created
        """
        logger.info(f"[Capture] Scanning procurement source: {source.name} ({source.url})")

        keywords = self._parse_keywords(source)
        if not keywords:
            keywords = self._get_active_keywords(db)

        try:
            from app.services.stealth_crawler import get_stealth_crawler, run_async
            crawler = get_stealth_crawler()
            result = run_async(
                crawler.crawl_listing(
                    listing_url=source.url,
                    keywords=keywords,
                    authenticated=True,
                )
            )
        except ImportError:
            logger.warning("[Capture] Scrapling not installed — stealth crawl skipped")
            return 0
        except Exception as e:
            logger.error(f"[Capture] Crawl failed for {source.url}: {e}")
            return 0

        created = 0
        for sub in result.get("sub_results", []):
            try:
                sol = self._process_sub_result(sub, source.url, keywords, db)
                if sol:
                    created += 1
            except Exception as e:
                logger.error(f"[Capture] Failed to process sub-result {sub.get('url')}: {e}")
                db.rollback()

        logger.info(f"[Capture] Created {created} new solicitation(s) from {source.name}")
        return created

    def scan_url(self, url: str, db) -> Optional[Any]:
        """
        Scrape and qualify a single solicitation URL (for manual one-off scans).
        Returns the created Solicitation or None if skipped/failed.
        """
        logger.info(f"[Capture] Manual scan of: {url}")
        keywords = self._get_active_keywords(db)

        try:
            from app.services.stealth_crawler import get_stealth_crawler, run_async
            crawler = get_stealth_crawler()
            sub = run_async(crawler.scrape_url(url))
        except Exception as e:
            logger.error(f"[Capture] Manual scrape failed for {url}: {e}")
            return None

        return self._process_sub_result(sub, url, keywords, db)

    # ── Internal: process one scraped sub-result ───────────────────────────────

    def _process_sub_result(
        self,
        sub: Dict[str, Any],
        source_url: str,
        keywords: List[str],
        db,
    ) -> Optional[Any]:
        """
        Given a scraped sub-result { url, markdown, pdf_contents },
        run qualification extraction and save a Solicitation record.
        """
        solicitation_url = sub.get("url", "")
        if not solicitation_url:
            return None

        # Deduplication
        if self._is_duplicate(solicitation_url, db):
            logger.debug(f"[Capture] Duplicate skipped: {solicitation_url}")
            return None

        # Build full text: markdown + all PDF contents
        markdown = sub.get("markdown", "") or ""
        pdf_contents: Dict[str, str] = sub.get("pdf_contents", {}) or {}
        full_text = self._build_full_text(markdown, pdf_contents)

        if len(full_text.strip()) < 100:
            logger.debug(f"[Capture] Too little content at {solicitation_url}, skipping")
            return None

        # Determine which keyword matched (from URL or content)
        matched_keyword = self._find_matched_keyword(solicitation_url + " " + full_text[:2000], keywords)

        # Run LLM extraction
        extraction = self._extract_qualification(full_text, matched_keyword, solicitation_url)
        if not extraction:
            return None

        # Scope gate: skip very low-match solicitations
        scope_pct = extraction.get("scope_match", {}) or {}
        if isinstance(scope_pct, dict):
            scope_pct_val = scope_pct.get("percentage", 0) or 0
        else:
            scope_pct_val = 0

        if scope_pct_val < MIN_SCOPE_MATCH_PCT:
            logger.info(
                f"[Capture] Scope match {scope_pct_val}% < {MIN_SCOPE_MATCH_PCT}% threshold, skipping"
            )
            return None

        # Save Solicitation
        sol = self._save_solicitation(
            extraction=extraction,
            solicitation_url=solicitation_url,
            source_url=source_url,
            raw_rfp_text=full_text,
            pdf_filenames=list(pdf_contents.keys()),
            keyword_matched=matched_keyword,
            db=db,
        )

        # Send notification
        if sol:
            try:
                self._notify(sol, db)
            except Exception as ne:
                logger.warning(f"[Capture] Notification failed: {ne}")

        return sol

    # ── LLM qualification ──────────────────────────────────────────────────────

    def _extract_qualification(
        self,
        full_text: str,
        keyword: str,
        solicitation_url: str,
    ) -> Optional[Dict]:
        """Run CAPTURE_QUALIFICATION_PROMPT against full_text via LLM."""
        from app.core.prompts import CAPTURE_QUALIFICATION_PROMPT
        from app.core.llm_client import get_llm_client

        max_chars = self.settings.CAPTURE_MAX_TEXT_CHARS
        truncated = full_text[:max_chars]

        prompt = CAPTURE_QUALIFICATION_PROMPT.format(
            keyword=keyword or "IT services",
            solicitation_url=solicitation_url,
            rfp_text=truncated,
        )

        provider = self.settings.CAPTURE_LLM_PROVIDER
        llm = get_llm_client()

        try:
            result = llm.generate_json(prompt, provider=provider)
            logger.info(
                f"[Capture] Qualification extracted: "
                f"title='{result.get('title', '')[:60]}' "
                f"scope={result.get('scope_match', {}).get('percentage', '?')}%"
            )
            return result
        except Exception as e:
            logger.error(f"[Capture] LLM qualification failed: {e}")
            # Fallback: try with a different provider
            if provider != "groq":
                try:
                    result = llm.generate_json(prompt, provider="groq")
                    return result
                except Exception as e2:
                    logger.error(f"[Capture] Fallback LLM also failed: {e2}")
            return None

    # ── DB persistence ─────────────────────────────────────────────────────────

    def _save_solicitation(
        self,
        extraction: Dict,
        solicitation_url: str,
        source_url: str,
        raw_rfp_text: str,
        pdf_filenames: List[str],
        keyword_matched: str,
        db,
    ):
        """Build and persist a Solicitation record from extracted data."""
        from app.models import Solicitation

        scope = extraction.get("scope_match") or {}
        scope_level = scope.get("level", "Low") if isinstance(scope, dict) else "Low"
        scope_pct = float(scope.get("percentage", 0) or 0) if isinstance(scope, dict) else 0.0
        scope_summary = scope.get("summary", "") if isinstance(scope, dict) else ""

        tech = extraction.get("technical_requirements")
        insurance = extraction.get("insurance_requirements")
        past_perf = extraction.get("past_performance_requirements")
        certs = extraction.get("certifications_required")
        licenses = extraction.get("licenses_registrations")
        mandatory = extraction.get("mandatory_disqualifying_requirements")
        win_signals = extraction.get("what_may_help_win")
        eval_matrix = extraction.get("evaluation_matrix")

        sol = Solicitation(
            source_url=source_url,
            solicitation_url=solicitation_url,
            title=extraction.get("title") or "",
            agency=extraction.get("agency") or "",
            solicitation_number=extraction.get("solicitation_number"),
            response_deadline=extraction.get("response_deadline"),
            keyword_matched=keyword_matched,
            keyword_matched_paragraph=extraction.get("keyword_matched_paragraph"),
            past_performance_section=json.dumps(past_perf) if past_perf is not None else None,
            insurance_section=json.dumps(insurance) if insurance is not None else None,
            certifications_section=json.dumps(certs) if certs is not None else None,
            licenses_section=json.dumps(licenses) if licenses is not None else None,
            mandatory_requirements=json.dumps(mandatory) if mandatory is not None else None,
            scope_match_level=scope_level,
            scope_match_percentage=scope_pct,
            scope_match_summary=scope_summary,
            technical_requirements=json.dumps(tech) if tech is not None else None,
            what_may_help_win=json.dumps(win_signals) if win_signals is not None else None,
            evaluation_matrix=json.dumps(eval_matrix) if eval_matrix is not None else None,
            raw_rfp_text=raw_rfp_text[:200000],   # cap stored text at 200k chars
            pdf_filenames=json.dumps(pdf_filenames),
            status="new",
        )

        db.add(sol)
        db.commit()
        db.refresh(sol)
        logger.info(
            f"[Capture] Saved solicitation id={sol.id}: "
            f"'{sol.title[:60]}' | {scope_level} match ({scope_pct}%)"
        )
        return sol

    # ── Notification ───────────────────────────────────────────────────────────

    def _notify(self, sol, db):
        """Send email + in-app notification for a new high/medium solicitation."""
        from app.services.notification_service import get_notification_service

        if sol.scope_match_level not in ("High", "Medium"):
            return

        title = f"New {sol.scope_match_level} Match Solicitation: {sol.title[:80]}"
        msg = (
            f"Agency: {sol.agency}\n"
            f"Scope Match: {sol.scope_match_level} ({sol.scope_match_percentage:.0f}%)\n"
            f"Deadline: {sol.response_deadline or 'Not specified'}\n"
            f"Keyword: {sol.keyword_matched}\n"
            f"URL: {sol.solicitation_url}"
        )
        svc = get_notification_service()
        svc.create_notification(title=title, message=msg, db=db)
        svc.send_email_alert(subject=title, body=msg)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _parse_keywords(self, source) -> List[str]:
        if source.keywords:
            try:
                return json.loads(source.keywords)
            except Exception:
                pass
        return []

    def _get_active_keywords(self, db) -> List[str]:
        """
        Return keywords from the active KeywordSet in DB.
        Falls back to settings.CAPTURE_KEYWORDS if none active.
        """
        try:
            from app.models import KeywordSet
            active = db.query(KeywordSet).filter(KeywordSet.is_active == True).first()
            if active:
                import json as _json
                kws = _json.loads(active.keywords) if active.keywords else []
                if kws:
                    return kws
        except Exception as e:
            logger.warning(f"[Capture] Could not load active keyword set: {e}")
        return [k.strip() for k in self.settings.CAPTURE_KEYWORDS.split(",") if k.strip()]

    def _build_full_text(self, markdown: str, pdf_contents: Dict[str, str]) -> str:
        parts = [markdown]
        if pdf_contents:
            parts.append("\n\n--- ATTACHED DOCUMENT CONTENTS ---")
            for fname, text in pdf_contents.items():
                if text and not text.startswith("[ERROR]"):
                    parts.append(f"\nFile: {fname}\n{text}")
        return "\n".join(parts)

    def _find_matched_keyword(self, text: str, keywords: List[str]) -> str:
        text_lower = text.lower()
        for kw in keywords:
            if kw.lower() in text_lower:
                return kw
        return keywords[0] if keywords else ""

    def _is_duplicate(self, solicitation_url: str, db) -> bool:
        from app.models import Solicitation
        cutoff = datetime.utcnow() - timedelta(days=30)
        existing = (
            db.query(Solicitation)
            .filter(
                Solicitation.solicitation_url == solicitation_url,
                Solicitation.created_at >= cutoff,
            )
            .first()
        )
        return existing is not None


# ── Singleton ──────────────────────────────────────────────────────────────────

_capture_service: Optional[CaptureService] = None


def get_capture_service() -> CaptureService:
    global _capture_service
    if _capture_service is None:
        _capture_service = CaptureService()
    return _capture_service
