"""
Portfolio matching service - matches job skills with company portfolio
"""
import logging
from typing import List
from app.core.vector_store import get_vector_store
from app.api.schemas import PortfolioMatch
from app.config import get_settings

logger = logging.getLogger(__name__)


class PortfolioMatcher:
    """Service for matching job skills with portfolio entries"""
    
    def __init__(self):
        """Initialize portfolio matcher"""
        settings = get_settings()
        self.vector_store = get_vector_store(
            persist_dir=settings.CHROMA_PERSIST_DIR,
            collection_name=settings.COLLECTION_NAME,
            embedding_model=settings.EMBEDDING_MODEL
        )
    
    def match_skills_to_portfolio(
        self,
        skills: List[str],
        top_k: int = 3
    ) -> List[PortfolioMatch]:
        """
        Match job skills with portfolio entries using vector search
        
        Args:
            skills: List of required job skills
            top_k: Number of matches per skill
            
        Returns:
            List of PortfolioMatch objects
        """
        try:
            logger.info(f"Matching {len(skills)} skills to portfolio")
            
            # Search vector store
            results = self.vector_store.search_skills(skills, top_k=top_k)
            
            logger.info(f"Raw vector search returned {len(results)} results")
            if results:
                logger.info(f"Sample raw results: {[(r['skill'], r['relevance_score']) for r in results[:3]]}")
            
            # Convert to PortfolioMatch objects
            matches = []
            for result in results:
                match = PortfolioMatch(
                    skill=result['skill'],
                    portfolio_link=result['portfolio_link'],
                    projects=result['projects'],
                    relevance_score=result['relevance_score']
                )
                matches.append(match)
            
            # Filter low relevance matches (threshold: 0.3 - lowered for broader matching)
            matches = [m for m in matches if m.relevance_score >= 0.25]
            
            logger.info(f"Found {len(matches)} high-quality portfolio matches")
            return matches
            
        except Exception as e:
            logger.error(f"Error matching skills to portfolio: {str(e)}")
            raise
    
    def format_matches_for_email(self, matches: List[PortfolioMatch]) -> str:
        """
        Format portfolio matches for inclusion in email
        
        Args:
            matches: List of portfolio matches
            
        Returns:
            Formatted string for email context
        """
        if not matches:
            return "No specific portfolio matches found."
        
        formatted_lines = []
        for match in matches[:5]:  # Limit to top 5 matches
            projects_str = ", ".join(match.projects[:3])  # Top 3 projects
            formatted_lines.append(
                f"- {match.skill}: We have expertise in {projects_str}. "
                f"See our work: {match.portfolio_link}"
            )
        
        return "\n".join(formatted_lines)
    
    def add_portfolio_entry(
        self,
        skill: str,
        portfolio_link: str,
        projects: List[str],
        description: str = ""
    ) -> str:
        """
        Add a new portfolio entry to the vector store
        
        Args:
            skill: Skill name
            portfolio_link: Portfolio URL
            projects: List of project names
            description: Optional description
            
        Returns:
            Document ID
        """
        try:
            doc_id = self.vector_store.add_portfolio(
                skill=skill,
                portfolio_link=portfolio_link,
                projects=projects,
                description=description
            )
            logger.info(f"Added portfolio entry for skill: {skill}")
            return doc_id
        except Exception as e:
            logger.error(f"Error adding portfolio entry: {str(e)}")
            raise


# Singleton instance
_portfolio_matcher = None


def get_portfolio_matcher() -> PortfolioMatcher:
    """Get or create portfolio matcher singleton"""
    global _portfolio_matcher
    if _portfolio_matcher is None:
        _portfolio_matcher = PortfolioMatcher()
    return _portfolio_matcher