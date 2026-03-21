"""
AI Personalization Service — extracts company context from website for hyper-personalized emails
"""
import logging
from typing import Optional
import requests
from bs4 import BeautifulSoup
from app.core.llm_client import get_llm_client
from app.core.prompts import COMPANY_CONTEXT_EXTRACTION_PROMPT
from app.utils.text_cleaner import clean_html_text

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/91.0.4472.124 Safari/537.36"
    )
}


class PersonalizationService:
    """Scrapes a company website and extracts context for email personalization."""

    def __init__(self):
        self.llm_client = get_llm_client()

    def get_context(self, company_url: str) -> str:
        """
        Scrape the company homepage and return a formatted context string
        suitable for injection into the email generation prompt.

        Args:
            company_url: URL of the company's website

        Returns:
            Short context string (≤500 chars), empty string on failure
        """
        try:
            raw_text = self._scrape(company_url)
            if not raw_text:
                return ""

            context = self._extract_context(raw_text)
            return context

        except Exception as e:
            logger.warning(f"Personalization failed for {company_url}: {e}")
            return ""

    def _scrape(self, url: str) -> str:
        """Scrape and clean text from the company homepage."""
        try:
            resp = requests.get(url, headers=HEADERS, timeout=8)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.content, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()

            text = soup.get_text()
            return clean_html_text(text)[:3000]  # limit before LLM

        except Exception as e:
            logger.debug(f"Scrape failed for {url}: {e}")
            return ""

    def _extract_context(self, website_text: str) -> str:
        """Use LLM to extract structured context from raw website text."""
        try:
            prompt = COMPANY_CONTEXT_EXTRACTION_PROMPT.format(website_text=website_text)
            result = self.llm_client.generate_json(prompt)

            parts = []
            if result.get("company_description"):
                parts.append(result["company_description"])
            if result.get("industry"):
                parts.append(f"Industry: {result['industry']}")
            if result.get("tech_stack"):
                parts.append(f"Tech stack: {', '.join(result['tech_stack'][:5])}")
            if result.get("recent_focus"):
                parts.append(result["recent_focus"])

            context = " | ".join(parts)
            return context[:500]

        except Exception as e:
            logger.debug(f"Context extraction LLM call failed: {e}")
            return ""


# Singleton
_personalization_service = None


def get_personalization_service() -> PersonalizationService:
    global _personalization_service
    if _personalization_service is None:
        _personalization_service = PersonalizationService()
    return _personalization_service
