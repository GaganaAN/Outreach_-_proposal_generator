"""
Email generation service - generates personalized cold emails
"""
import logging
from typing import List
from app.core.llm_client import get_llm_client
from app.core.prompts import EMAIL_GENERATION_PROMPT, EMAIL_SUBJECT_PROMPT
from app.api.schemas import JobDetails, PortfolioMatch
from app.config import get_settings
from app.utils.text_cleaner import extract_email_safe_text, clean_email_body
import re

logger = logging.getLogger(__name__)


class EmailGenerator:
    """Service for generating cold emails"""
    
    def __init__(self):
        """Initialize email generator"""
        self.llm_client = get_llm_client()
        self.settings = get_settings()
    
    def generate_email_subject(
        self,
        job_role: str,
        key_skills: List[str]
    ) -> str:
        """
        Generate compelling email subject line
        
        Args:
            job_role: Job title
            key_skills: Top 3-4 key skills
            
        Returns:
            Email subject line
        """
        try:
            prompt = EMAIL_SUBJECT_PROMPT.format(
                job_role=job_role,
                key_skills=", ".join(key_skills[:4])
            )
            
            subject = self.llm_client.generate(prompt, max_tokens=100)
            
            # Clean and truncate
            subject = extract_email_safe_text(subject).strip()
            subject = subject.replace('"', '').replace("'", "")
            
            if len(subject) > 100:
                subject = subject[:97] + "..."
            
            logger.info(f"Generated subject: {subject}")
            return subject
            
        except Exception as e:
            logger.error(f"Error generating subject: {str(e)}")
            # Fallback subject
            return f"Expert {job_role} Team Available - {key_skills[0] if key_skills else 'Tech'} Specialists"
    
    def format_portfolio_matches(self, matches: List[PortfolioMatch]) -> str:
        """
        Format portfolio matches for LLM context
        
        Args:
            matches: List of portfolio matches
            
        Returns:
            Formatted string
        """
        if not matches:
            return "No specific portfolio matches available."
        
        formatted = []
        for i, match in enumerate(matches[:5], 1):
            projects = ", ".join(match.projects[:3])
            formatted.append(
                f"{i}. {match.skill} (Relevance: {match.relevance_score:.2f})\n"
                f"   Portfolio: {match.portfolio_link}\n"
                f"   Projects: {projects}"
            )
        
        return "\n".join(formatted)
    
    def generate_email_body(
        self,
        job_details: JobDetails,
        portfolio_matches: List[PortfolioMatch]
    ) -> str:
        """
        Generate email body content
        
        Args:
            job_details: Structured job information
            portfolio_matches: Matched portfolio entries
            
        Returns:
            Email body text
        """
        try:
            logger.info("Generating email body with LLM")
            print("DEBUG: Generating email body...") # Force stdout
            
            # Format portfolio matches
            portfolio_context = self.format_portfolio_matches(portfolio_matches)
            
            # Create prompt
            prompt = EMAIL_GENERATION_PROMPT.format(
                company_name=self.settings.COMPANY_NAME,
                company_website=self.settings.COMPANY_WEBSITE,
                job_role=job_details.job_role,
                skills=", ".join(job_details.skills),
                job_description=job_details.description,
                portfolio_matches=portfolio_context
            )
            
            # Generate email
            email_body = self.llm_client.generate(
                prompt,
                temperature=0.7,  # More creative for email writing
                max_tokens=800  # Reduced for more concise emails (was 1500)
            )
            
            # Clean and format email text - preserve newlines!
            email_body = clean_email_body(email_body)
            
            # Remove "Subject:" or leading "Best regards" if they appear at start
            lines = email_body.split('\n')
            
            # Filter out subject line or premature greeting
            clean_lines = []
            skip = True
            for line in lines:
                lower_line = line.lower().strip()
                if skip:
                    if lower_line.startswith('subject:'):
                        continue
                    if lower_line.startswith('best regards'):
                        continue
                    if not line.strip(): # Skip leading empty lines
                        continue
                    skip = False # Found content start
                
                clean_lines.append(line)
            
            email_body = '\n'.join(clean_lines).strip()
            
            # Standardize signature
            # Find the last occurrence of "Best regards" to ensure we're targeting the signature
            signature_pattern = r'(Best|Kind)\s*regards,?'
            matches = list(re.finditer(signature_pattern, email_body, re.IGNORECASE))
            
            if matches:
                 print("DEBUG: Found signature match")
                 logger.info("Found signature to standardize")
                 last_match = matches[-1]
                 # Truncate at the signature start and append clean version
                 email_body = email_body[:last_match.start()].rstrip()
                 email_body += (
                     f"\n\nBest regards,\n\n"
                     f"Business Development Team\n\n"
                     f"{self.settings.COMPANY_NAME}\n\n"
                     f"{self.settings.COMPANY_WEBSITE}"
                 )
            else:
                 print(f"DEBUG: No signature match found. Body end: {email_body[-50:]}")
                 logger.warning("No 'Best regards' signature found - appending default")
                 email_body += (
                     f"\n\nBest regards,\n\n"
                     f"Business Development Team\n\n"
                     f"{self.settings.COMPANY_NAME}\n\n"
                     f"{self.settings.COMPANY_WEBSITE}"
                 )
            
            # Clean up excessive line breaks
            email_body = re.sub(r'\n{4,}', '\n\n\n', email_body)
            
            logger.info(f"Generated email body ({len(email_body)} chars)")
            return email_body
            
        except Exception as e:
            logger.error(f"Error generating email body: {str(e)}")
            raise
    
    def generate_complete_email(
        self,
        job_details: JobDetails,
        portfolio_matches: List[PortfolioMatch]
    ) -> dict:
        """
        Generate complete email (subject + body)
        
        Args:
            job_details: Structured job information
            portfolio_matches: Matched portfolio entries
            
        Returns:
            Dict with email_subject and email_body
        """
        try:
            # Generate subject
            subject = self.generate_email_subject(
                job_details.job_role,
                job_details.skills
            )
            
            # Generate body
            body = self.generate_email_body(job_details, portfolio_matches)
            
            return {
                "email_subject": subject,
                "email_body": body
            }
            
        except Exception as e:
            logger.error(f"Error generating complete email: {str(e)}")
            raise


# Singleton instance
_email_generator = None


def get_email_generator() -> EmailGenerator:
    """Get or create email generator singleton"""
    global _email_generator
    if _email_generator is None:
        _email_generator = EmailGenerator()
    return _email_generator