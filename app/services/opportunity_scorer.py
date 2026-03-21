"""
Opportunity Scoring Service — scores leads based on skill match and signal strength
"""
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


class OpportunityScorer:
    """Scores an opportunity by matching detected skills against portfolio."""

    def score_from_skills(self, skills: List[str]) -> Dict[str, float]:
        """
        Score based on how well skills match the portfolio.

        Returns dict with skill_match_score (0-1).
        """
        if not skills:
            return {"skill_match_score": 0.0}

        try:
            from app.services.portfolio_matcher import get_portfolio_matcher
            matcher = get_portfolio_matcher()
            matches = matcher.match_skills_to_portfolio(skills, top_k=3)

            if not matches:
                return {"skill_match_score": 0.0}

            avg_score = sum(m.relevance_score for m in matches) / len(matches)
            return {"skill_match_score": round(min(1.0, avg_score), 3)}

        except Exception as e:
            logger.warning(f"Skill matching for scoring failed: {e}")
            return {"skill_match_score": 0.0}

    @staticmethod
    def compute_priority(overall_score: float) -> str:
        if overall_score >= 0.7:
            return "high"
        elif overall_score >= 0.4:
            return "medium"
        return "low"

    @staticmethod
    def compute_overall(skill_match: float, signal_strength: float) -> float:
        return round(0.6 * skill_match + 0.4 * signal_strength, 3)


# Singleton
_scorer = None


def get_opportunity_scorer() -> OpportunityScorer:
    global _scorer
    if _scorer is None:
        _scorer = OpportunityScorer()
    return _scorer
