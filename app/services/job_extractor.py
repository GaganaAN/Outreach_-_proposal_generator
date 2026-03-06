"""
Job extraction service - scrapes and extracts structured job information
"""
import logging
import requests
from typing import Dict, Any
from bs4 import BeautifulSoup
from app.core.llm_client import get_llm_client
from app.core.prompts import JOB_EXTRACTION_PROMPT
from app.utils.text_cleaner import clean_html_text, extract_job_section, normalize_skill
from app.api.schemas import JobDetails

logger = logging.getLogger(__name__)


class JobExtractor:
    """Service for extracting job information from URLs"""
    
    def __init__(self):
        """Initialize job extractor"""
        self.llm_client = get_llm_client()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    
    def scrape_job_page(self, url: str) -> str:
        """
        Scrape job posting page and extract text content
        
        Args:
            url: Job posting URL
            
        Returns:
            Extracted text content
        """
        try:
            logger.info(f"Scraping job page: {url}")
            
            # Fetch page
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            
            # Parse HTML
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Remove script and style elements
            for script in soup(["script", "style", "nav", "footer", "header"]):
                script.decompose()
            
            # Get text
            text = soup.get_text()
            
            # Clean text
            text = clean_html_text(text)
            
            # Extract relevant job section
            text = extract_job_section(text)
            
            logger.info(f"Extracted {len(text)} characters from job page")
            return text
            
        except requests.RequestException as e:
            logger.error(f"Failed to scrape job page: {str(e)}")
            raise Exception(f"Failed to fetch job page: {str(e)}")
        except Exception as e:
            logger.error(f"Error scraping job page: {str(e)}")
            raise
    
    def extract_job_details(self, job_text: str) -> JobDetails:
        """
        Extract structured job details using LLM
        
        Args:
            job_text: Raw job posting text
            
        Returns:
            Structured JobDetails object
        """
        try:
            logger.info("Extracting job details with LLM")
            
            # Create prompt
            prompt = JOB_EXTRACTION_PROMPT.format(job_text=job_text)
            
            # Get LLM response
            result = self.llm_client.generate_json(prompt)
            
            # Validate and fix the result
            # Ensure skills is always a list, never None
            if not result.get('skills') or result.get('skills') is None:
                logger.warning("No skills found in LLM response, using default skills")
                result['skills'] = ["Communication", "Problem Solving", "Teamwork"]
            
            # Ensure skills is a list
            if not isinstance(result['skills'], list):
                logger.warning(f"Skills is not a list: {result['skills']}, converting")
                result['skills'] = [str(result['skills'])]
            
            # Remove empty skills
            result['skills'] = [s for s in result['skills'] if s and str(s).strip()]
            
            # If still empty, add default
            if not result['skills']:
                result['skills'] = ["General Skills"]
            
            # Normalize skills
            result['skills'] = [normalize_skill(skill) for skill in result['skills']]
            
            # Ensure required fields exist
            if not result.get('job_role'):
                result['job_role'] = 'Position'
            
            if not result.get('description'):
                result['description'] = 'No description available'
            
            # Create JobDetails object
            job_details = JobDetails(
                job_role=result.get('job_role', 'Unknown Role'),
                skills=result.get('skills', []),
                description=result.get('description', ''),
                experience_level=result.get('experience_level'),
                location=result.get('location')
            )
            
            logger.info(f"Extracted job: {job_details.job_role} with {len(job_details.skills)} skills")
            return job_details
            
        except Exception as e:
            logger.error(f"Error extracting job details: {str(e)}")
            # Return a fallback JobDetails instead of raising
            logger.warning("Returning fallback job details due to extraction error")
            return JobDetails(
                job_role="Position",
                skills=["Please review manually"],
                description="Unable to extract job details automatically. Please review the job posting manually.",
                experience_level=None,
                location=None
            )
    
    def process_job_url(self, url: str) -> Dict[str, Any]:
        """
        Complete pipeline: scrape page and extract job details
        
        Args:
            url: Job posting URL
            
        Returns:
            Dict containing job_details and raw_text_length
        """
        try:
            # Scrape page
            raw_text = self.scrape_job_page(url)
            
            # Extract details
            job_details = self.extract_job_details(raw_text)
            
            return {
                "job_details": job_details,
                "raw_text_length": len(raw_text)
            }
            
        except Exception as e:
            logger.error(f"Error processing job URL: {str(e)}")
            raise


# Singleton instance
_job_extractor = None


def get_job_extractor() -> JobExtractor:
    """Get or create job extractor singleton"""
    global _job_extractor
    if _job_extractor is None:
        _job_extractor = JobExtractor()
    return _job_extractor