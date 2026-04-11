"""
Proposal Generation Service — generates structured technical proposals from RFP text.

Two entry points:
  generate()                  — manual RFP upload (existing behaviour, preserved)
  generate_from_solicitation() — from a qualified Solicitation record (Capture pipeline)

Uses past performance data for evidence-based proposals.
"""
import logging
import json
from typing import Optional, List
from app.core.llm_client import get_llm_client
from app.core.prompts import RFP_EXTRACTION_PROMPT, PROPOSAL_GENERATION_PROMPT
from app.config import get_settings

logger = logging.getLogger(__name__)


class ProposalGenerator:
    """Generates a structured technical proposal from parsed RFP text."""

    def __init__(self):
        self.llm_client = get_llm_client()
        self.settings = get_settings()

    def extract_requirements(self, rfp_text: str, llm_provider: str = None) -> dict:
        """
        Use LLM to extract structured requirements from RFP text.

        Returns:
            Dict with project_title, client_name, requirements list, tech_stack, etc.
        """
        try:
            # Increased from 5000 chars to 100000 to handle real RFP documents
            truncated = rfp_text[:100000]
            prompt = RFP_EXTRACTION_PROMPT.format(rfp_text=truncated)
            result = self.llm_client.generate_json(prompt, provider=llm_provider)

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

    def _find_relevant_past_projects(
        self,
        tech_stack: List[str],
        requirements: List[str],
        db,
        top_k: int = 3,
    ) -> List[dict]:
        """
        Query PastProject table and return projects matching RFP's tech_stack / requirements.

        Returns:
            List of matched PastProject.to_dict() records (up to top_k).
            Empty list if none found or db unavailable.
        """
        if db is None:
            return []
        try:
            from app.models import PastProject

            projects = db.query(PastProject).filter(PastProject.is_active == True).all()
            if not projects:
                return []

            # Build keyword set from RFP tech_stack + first 10 requirements
            keywords = set()
            for t in tech_stack:
                keywords.update(t.lower().split())
            for r in requirements[:10]:
                keywords.update(r.lower().split())
            # Remove very common words
            stopwords = {"and", "or", "the", "a", "an", "for", "to", "of", "in", "with", "on", "is", "be", "are"}
            keywords -= stopwords

            scored = []
            for proj in projects:
                score = 0
                proj_techs = json.loads(proj.technologies) if proj.technologies else []
                proj_text = " ".join([
                    proj.project_type or "",
                    proj.industry or "",
                    proj.problem_statement or "",
                    proj.our_solution or "",
                    " ".join(proj_techs),
                ]).lower()

                for kw in keywords:
                    if len(kw) >= 3 and kw in proj_text:
                        score += 1

                if score > 0:
                    scored.append((score, proj))

            # Sort by score descending, take top_k
            scored.sort(key=lambda x: x[0], reverse=True)
            return [p.to_dict() for _, p in scored[:top_k]]

        except Exception as e:
            logger.warning(f"Past project matching failed: {e}")
            return []

    def _format_past_projects(self, projects: List[dict]) -> str:
        """Format past projects into a readable string for the prompt."""
        if not projects:
            return "No matching past performance data available."
        lines = []
        for p in projects:
            techs = ", ".join(p.get("technologies", []))
            lines.append(
                f"• {p['title']} ({p.get('project_type', '')})\n"
                f"  Client: {p.get('client_name', 'Confidential')} | Industry: {p.get('industry', '')}\n"
                f"  Technologies: {techs}\n"
                f"  Outcome: {p.get('outcome', '')}"
            )
        return "\n\n".join(lines)

    def generate(
        self,
        rfp_text: str,
        opportunity_id: Optional[int] = None,
        llm_provider: Optional[str] = None,
        db=None,
    ) -> dict:
        """
        Full pipeline: extract requirements → match portfolio + past projects → generate proposal.

        Args:
            rfp_text:        Parsed RFP text
            opportunity_id:  Optional linked opportunity ID
            llm_provider:    LLM to use (groq | openai | gemini | None → default)
            db:              SQLAlchemy session for past project lookup

        Returns:
            Dict with requirements (list) and proposal_content (dict of sections).
            Returns {"no_match": True, "message": ...} if no past projects match.
        """
        # Step 1: Extract requirements
        extraction = self.extract_requirements(rfp_text, llm_provider=llm_provider)
        requirements = extraction.get("requirements", [])
        tech_stack = extraction.get("tech_stack", [])

        # Step 2: Find relevant past performance projects
        past_projects = self._find_relevant_past_projects(tech_stack, requirements, db)

        if db is not None and not past_projects:
            logger.info("No matching past performance found for this RFP — returning no_match")
            return {
                "no_match": True,
                "message": (
                    "No matching past performance data found for this RFP's technology stack. "
                    "Please add relevant projects in Past Performance to generate a proposal."
                ),
                "extraction": extraction,
                "requirements": requirements,
            }

        past_projects_str = self._format_past_projects(past_projects)

        # Step 3: Match with portfolio (ChromaDB)
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

        # Step 4: Generate proposal sections
        requirements_str = "\n".join(f"- {r}" for r in requirements) or "Not specified"
        try:
            prompt = PROPOSAL_GENERATION_PROMPT.format(
                company_name=self.settings.COMPANY_NAME,
                company_website=self.settings.COMPANY_WEBSITE,
                requirements=requirements_str,
                portfolio_matches=portfolio_context,
                past_projects=past_projects_str,
                evaluation_matrix="Not specified",
                what_may_help_win="[]",
            )
            proposal_sections = self.llm_client.generate_json(prompt, provider=llm_provider)
        except Exception as e:
            logger.error(f"Proposal generation LLM call failed: {e}")
            proposal_sections = {
                "executive_summary": "Unable to generate proposal. Please try again.",
                "error": str(e),
            }

        logger.info(f"Proposal generated with {len(proposal_sections)} sections (opportunity_id={opportunity_id})")
        return {
            "extraction":       extraction,
            "requirements":     requirements,
            "proposal_content": proposal_sections,
            "past_projects":    past_projects,
        }

    def generate_from_solicitation(
        self,
        solicitation,
        llm_provider: Optional[str] = None,
        db=None,
    ) -> dict:
        """
        Generate a technical proposal from a qualified Solicitation record.

        Differences from generate():
        - Uses full rfp_text (no truncation beyond CAPTURE_MAX_TEXT_CHARS)
        - Skips re-extraction: uses pre-qualified technical_requirements section
        - Injects evaluation_matrix and what_may_help_win into the prompt
        - Links the resulting Proposal back to the Solicitation

        Args:
            solicitation: Solicitation ORM instance (status should be 'bid')
            llm_provider: override LLM provider
            db:           SQLAlchemy session

        Returns:
            Dict with requirements, proposal_content, past_projects
        """
        logger.info(f"[ProposalGenerator] Generating from solicitation id={solicitation.id}")

        # Step 1: Extract requirements from the already-qualified technical_requirements section
        tech_req_raw = solicitation.technical_requirements
        tech_req: dict = {}
        if tech_req_raw:
            try:
                tech_req = json.loads(tech_req_raw) if isinstance(tech_req_raw, str) else tech_req_raw
            except Exception:
                tech_req = {}

        technologies: List[str] = tech_req.get("technologies", []) or []
        work_desc: str = tech_req.get("work_description", "") or ""
        exact_exp: str = tech_req.get("exact_expectations", "") or ""

        # Build requirements list from technical_requirements
        requirements: List[str] = []
        if work_desc:
            requirements.append(work_desc)
        if exact_exp:
            for line in exact_exp.split("\n"):
                line = line.strip().lstrip("•-").strip()
                if len(line) > 20:
                    requirements.append(line)
        if not requirements:
            requirements = [solicitation.title or "Requirements not specified"]

        # Step 2: Past performance matching using tech stack from solicitation
        past_projects = self._find_relevant_past_projects(technologies, requirements, db)

        if db is not None and not past_projects:
            logger.info(
                f"[ProposalGenerator] No matching past performance for solicitation "
                f"id={solicitation.id} — returning no_match"
            )
            return {
                "no_match": True,
                "message": (
                    "No matching past performance data found for this solicitation's "
                    "technology stack. Please add relevant projects in Past Performance."
                ),
                "solicitation_id": solicitation.id,
                "requirements": requirements,
            }

        past_projects_str = self._format_past_projects(past_projects)

        # Step 3: Portfolio matching
        portfolio_context = "No portfolio matches found."
        skills_to_match = requirements[:5] + technologies[:5]
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
                logger.warning(f"Portfolio matching skipped: {match_err}")

        # Step 4: Build prompt with evaluation matrix + win signals from Solicitation
        requirements_str = "\n".join(f"- {r}" for r in requirements) or "Not specified"

        eval_matrix_raw = solicitation.evaluation_matrix
        eval_matrix_str = "Not specified"
        if eval_matrix_raw:
            try:
                em = json.loads(eval_matrix_raw) if isinstance(eval_matrix_raw, str) else eval_matrix_raw
                if isinstance(em, dict):
                    eval_matrix_str = (
                        f"Factors: {', '.join(em.get('factors', []))}\n"
                        f"Technical weight: {em.get('technical_weight', 'N/A')}\n"
                        f"Past performance weight: {em.get('past_performance_weight', 'N/A')}\n"
                        f"Price weight: {em.get('price_weight', 'N/A')}\n"
                        f"Scoring: {em.get('scoring_criteria', 'N/A')}"
                    )
            except Exception:
                pass

        win_signals_raw = solicitation.what_may_help_win
        win_signals_str = "[]"
        if win_signals_raw:
            try:
                ws = json.loads(win_signals_raw) if isinstance(win_signals_raw, str) else win_signals_raw
                if isinstance(ws, list):
                    win_signals_str = "\n".join(f"- {s}" for s in ws)
            except Exception:
                pass

        try:
            prompt = PROPOSAL_GENERATION_PROMPT.format(
                company_name=self.settings.COMPANY_NAME,
                company_website=self.settings.COMPANY_WEBSITE,
                requirements=requirements_str,
                portfolio_matches=portfolio_context,
                past_projects=past_projects_str,
                evaluation_matrix=eval_matrix_str,
                what_may_help_win=win_signals_str,
            )
            proposal_sections = self.llm_client.generate_json(prompt, provider=llm_provider)
        except Exception as e:
            logger.error(f"Proposal generation from solicitation failed: {e}")
            proposal_sections = {
                "executive_summary": "Unable to generate proposal. Please try again.",
                "error": str(e),
            }

        logger.info(
            f"[ProposalGenerator] Generated {len(proposal_sections)} sections "
            f"from solicitation id={solicitation.id}"
        )
        return {
            "solicitation_id":  solicitation.id,
            "requirements":     requirements,
            "proposal_content": proposal_sections,
            "past_projects":    past_projects,
        }


# Singleton
_proposal_generator = None


def get_proposal_generator() -> ProposalGenerator:
    global _proposal_generator
    if _proposal_generator is None:
        _proposal_generator = ProposalGenerator()
    return _proposal_generator
