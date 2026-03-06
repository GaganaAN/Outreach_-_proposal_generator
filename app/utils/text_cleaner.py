"""
Text cleaning and preprocessing utilities
"""
import re
from typing import Optional


def clean_html_text(text: str) -> str:
    """
    Clean HTML text by removing extra whitespace and formatting
    
    Args:
        text: Raw text extracted from HTML
        
    Returns:
        Cleaned text
    """
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text)
    
    # Remove leading/trailing whitespace
    text = text.strip()
    
    # Remove multiple newlines
    text = re.sub(r'\n+', '\n', text)
    
    return text


def extract_job_section(text: str, max_length: int = 5000) -> str:
    """
    Extract relevant job description section from full page text
    
    Args:
        text: Full page text
        max_length: Maximum length to extract
        
    Returns:
        Relevant job description text
    """
    # Common job section markers
    markers = [
        "job description",
        "responsibilities",
        "requirements",
        "qualifications",
        "about the role",
        "what you'll do",
        "who you are"
    ]
    
    text_lower = text.lower()
    
    # Find the earliest marker
    start_pos = len(text)
    for marker in markers:
        pos = text_lower.find(marker)
        if pos != -1 and pos < start_pos:
            start_pos = pos
    
    # If no marker found, use full text
    if start_pos == len(text):
        start_pos = 0
    
    # Extract section
    extracted = text[start_pos:start_pos + max_length]
    
    return clean_html_text(extracted)


def normalize_skill(skill: str) -> str:
    """
    Normalize skill name for consistency
    
    Args:
        skill: Raw skill name
        
    Returns:
        Normalized skill name
    """
    # Remove extra whitespace
    skill = skill.strip()
    
    # Capitalize properly
    # Common exceptions
    exceptions = {
        'api': 'API',
        'rest': 'REST',
        'sql': 'SQL',
        'nosql': 'NoSQL',
        'html': 'HTML',
        'css': 'CSS',
        'javascript': 'JavaScript',
        'typescript': 'TypeScript',
        'nodejs': 'Node.js',
        'reactjs': 'React',
        'vuejs': 'Vue.js',
        'aws': 'AWS',
        'gcp': 'GCP',
        'ml': 'ML',
        'ai': 'AI',
        'nlp': 'NLP',
        'ui': 'UI',
        'ux': 'UX'
    }
    
    skill_lower = skill.lower()
    if skill_lower in exceptions:
        return exceptions[skill_lower]
    
    return skill.title()


def truncate_text(text: str, max_length: int = 500, suffix: str = "...") -> str:
    """
    Truncate text to maximum length with suffix
    
    Args:
        text: Text to truncate
        max_length: Maximum length
        suffix: Suffix to add if truncated
        
    Returns:
        Truncated text
    """
    if len(text) <= max_length:
        return text
    
    return text[:max_length - len(suffix)].rsplit(' ', 1)[0] + suffix


def extract_email_safe_text(text: str) -> str:
    """
    Extract email-safe text (remove special characters that might break email formatting)
    
    Args:
        text: Raw text
        
    Returns:
        Email-safe text
    """
    # Remove excessive punctuation
    text = re.sub(r'([!?.]){2,}', r'\1', text)
    
    # Remove special characters that might break email
    text = re.sub(r'[^\w\s.,!?;:()\-\'"@/]', '', text)
    
    return clean_html_text(text)


def clean_email_body(text: str) -> str:
    """
    Clean email body text while preserving structure/newlines
    
    Args:
        text: Raw email body text
        
    Returns:
        Cleaned text with preserved paragraphs
    """
    # Remove excessive punctuation
    text = re.sub(r'([!?.]){2,}', r'\1', text)
    
    # Remove special characters but keep structure chars
    text = re.sub(r'[^\w\s.,!?;:()\-\'"@/\n]', '', text)
    
    # Normalize spaces within lines but keep newlines
    lines = []
    for line in text.split('\n'):
        # Clean within line
        clean_line = re.sub(r'\s+', ' ', line).strip()
        lines.append(clean_line)
    
    # Join with newlines
    text = '\n'.join(lines)
    
    # Fix multiple newlines (max 2)
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()