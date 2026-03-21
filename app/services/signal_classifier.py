"""
Signal Classification Service — classifies internet signals into sales action types
"""
import logging
import json
from typing import Optional
from dataclasses import dataclass, field
from app.core.llm_client import get_llm_client
from app.core.prompts import SIGNAL_CLASSIFICATION_PROMPT
from app.utils.text_cleaner import clean_html_text

logger = logging.getLogger(__name__)

VALID_SIGNAL_TYPES = {"job_hiring", "rfp_opportunity", "service_request", "other"}


@dataclass
class SignalResult:
    signal_type: str
    company_name: Optional[str]
    detected_skills: list
    confidence_score: float
    reasoning: str
    raw_text: str = ""
    source_url: Optional[str] = None


class SignalClassifier:
    """Classifies internet signals to determine sales routing."""

    def __init__(self):
        self.llm_client = get_llm_client()

    def _scrape_url(self, url: str) -> str:
        """Scrape text from a URL using existing infrastructure."""
        try:
            from app.services.job_extractor import get_job_extractor
            extractor = get_job_extractor()
            return extractor.scrape_job_page(url)
        except Exception as e:
            logger.warning(f"Could not scrape URL {url}: {e}")
            return ""

    def classify(self, input_text: str, source_url: Optional[str] = None) -> SignalResult:
        """
        Classify a signal from text or URL.

        Args:
            input_text: Raw text or a URL string
            source_url:  Explicit source URL (overrides auto-detection)

        Returns:
            SignalResult with type, skills, confidence, etc.
        """
        url = source_url
        raw_text = input_text.strip()

        # If input looks like a URL, scrape it
        if raw_text.startswith("http://") or raw_text.startswith("https://"):
            url = url or raw_text
            logger.info(f"Input is a URL, scraping: {url}")
            scraped = self._scrape_url(url)
            if scraped:
                raw_text = scraped
            else:
                logger.warning("Scraping returned empty text; classifying URL string directly")

        if not raw_text:
            return SignalResult(
                signal_type="other",
                company_name=None,
                detected_skills=[],
                confidence_score=0.0,
                reasoning="Empty input provided",
                raw_text=raw_text,
                source_url=url,
            )

        # Truncate to avoid exceeding token limits
        truncated_text = raw_text[:4000]

        try:
            prompt = SIGNAL_CLASSIFICATION_PROMPT.format(signal_text=truncated_text)
            result = self.llm_client.generate_json(prompt)

            signal_type = result.get("signal_type", "other")
            if signal_type not in VALID_SIGNAL_TYPES:
                signal_type = "other"

            skills = result.get("detected_skills", [])
            if not isinstance(skills, list):
                skills = []

            confidence = float(result.get("confidence_score", 0.5))
            confidence = max(0.0, min(1.0, confidence))

            return SignalResult(
                signal_type=signal_type,
                company_name=result.get("company_name"),
                detected_skills=skills,
                confidence_score=confidence,
                reasoning=result.get("reasoning", ""),
                raw_text=raw_text[:2000],  # store truncated version
                source_url=url,
            )

        except Exception as e:
            logger.error(f"Signal classification failed: {e}")
            return SignalResult(
                signal_type="other",
                company_name=None,
                detected_skills=[],
                confidence_score=0.0,
                reasoning=f"Classification error: {str(e)}",
                raw_text=raw_text[:2000],
                source_url=url,
            )


# Singleton
_signal_classifier = None


def get_signal_classifier() -> SignalClassifier:
    global _signal_classifier
    if _signal_classifier is None:
        _signal_classifier = SignalClassifier()
    return _signal_classifier
