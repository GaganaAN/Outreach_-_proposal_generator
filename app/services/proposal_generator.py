"""
Proposal Generation Service — generates structured technical proposals from RFP text
"""
import logging
import json
from typing import Optional
from app.core.llm_client import get_llm_client
from app.core.prompts import RFP_EXTRACTION_PROMPT, PROPOSAL_GENERATION_PROMPT
from app.config import get_settings

logger = logging.getLogger(__name__)


class ProposalGenerator:
    """Generates a structured technical proposal from parsed RFP text."""

    def __init__(self):
        self.llm_client = get_llm_client()
        self.settings = get_settings()

    def extract_requirements(self, rfp_text: str) -> dict:
        """
        Use LLM to extract structured requirements from RFP text.

        Returns:
            Dict with project_title, client_name, requirements list, tech_stack, etc.
        """
        try:
            truncated = rfp_text[:5000]
            prompt = RFP_EXTRACTION_PROMPT.format(rfp_text=truncated)
            result = self.llm_client.generate_json(prompt)

            # Ensure requirements is always a list
            if not isinstance(result.get("requirements"), list):
                result["requirements"] = []
            if not isinstance(result.get("tech_stack"), list):
                result["tech_stack"] = []

            logger.info(
                f"Extracted {len(result.get('requirements', []))} requirements "
                f"from RFP ({len(rfp_text)} chars)"
            )
            return result

        except Exception as e:
            logger.error(f"Requirement extraction failed: {e}")
            return {
                "project_title": "Unknown Project",
                "client_name": None,
                "requirements": [],
                "tech_stack": [],
                "timeline": None,
                "budget_range": None,
                "submission_deadline": None,
                "evaluation_criteria": [],
            }

    def generate(self, rfp_text: str, opportunity_id: Optional[int] = None) -> dict:
        """
        Full pipeline: extract requirements → match portfolio → generate proposal.

        Args:
            rfp_text:        Parsed RFP text
            opportunity_id:  Optional linked opportunity ID

        Returns:
            Dict with requirements (list) and proposal_content (dict of sections)
        """
        # Step 1: Extract requirements
        extraction = self.extract_requirements(rfp_text)
        requirements = extraction.get("requirements", [])
        tech_stack = extraction.get("tech_stack", [])

        # Step 2: Match with portfolio
        portfolio_context = "No portfolio matches found."
        skills_to_match = requirements[:5] + tech_stack[:5]
        if skills_to_match:
            try:
                from app.services.portfolio_matcher import get_portfolio_matcher
                matcher = get_portfolio_matcher()
                matches = matcher.match_skills_to_portfolio(skills_to_match, top_k=3)
                if matches:
                    lines = []
                    for m in matches[:5]:
                        projects = ", ".join(m.projects[:3])
                        lines.append(
                            f"- {m.skill} (score: {m.relevance_score:.2f}): "
                            f"{projects}. Portfolio: {m.portfolio_link}"
                        )
                    portfolio_context = "\n".join(lines)
            except Exception as match_err:
                logger.warning(f"Portfolio matching for proposal skipped: {match_err}")

        # Step 3: Generate proposal sections
        requirements_str = "\n".join(f"- {r}" for r in requirements) or "Not specified"
        try:
            prompt = PROPOSAL_GENERATION_PROMPT.format(
                company_name=self.settings.COMPANY_NAME,
                company_website=self.settings.COMPANY_WEBSITE,
                requirements=requirements_str,
                portfolio_matches=portfolio_context,
            )
            proposal_sections = self.llm_client.generate_json(prompt)
        except Exception as e:
            logger.error(f"Proposal generation LLM call failed: {e}")
            proposal_sections = {
                "executive_summary": "Unable to generate proposal. Please try again.",
                "error": str(e),
            }

        logger.info(f"Proposal generated with {len(proposal_sections)} sections")
        return {
            "extraction":       extraction,
            "requirements":     requirements,
            "proposal_content": proposal_sections,
        }


# Singleton
_proposal_generator = None


def get_proposal_generator() -> ProposalGenerator:
    global _proposal_generator
    if _proposal_generator is None:
        _proposal_generator = ProposalGenerator()
    return _proposal_generator
