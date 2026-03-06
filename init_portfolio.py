"""
Script to initialize the portfolio database with sample data
"""
import sys
import csv
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from app.core.vector_store import get_vector_store
from app.config import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_portfolio_from_csv(csv_path: str):
    """Load portfolio data from CSV file into vector store"""
    try:
        vector_store = get_vector_store()
        settings = get_settings()
        
        logger.info(f"Loading portfolio data from {csv_path}")
        
        # Read CSV
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            entries = list(reader)
        
        logger.info(f"Found {len(entries)} portfolio entries")
        
        # Add each entry to vector store
        for entry in entries:
            projects = entry['projects'].split(', ')
            
            vector_store.add_portfolio(
                skill=entry['skill'],
                portfolio_link=entry['portfolio_link'],
                projects=projects,
                description=entry['description']
            )
            
            logger.info(f"✓ Added: {entry['skill']}")
        
        total_docs = vector_store.count_documents()
        logger.info(f"✓ Portfolio initialized with {total_docs} documents")
        
        return total_docs
        
    except Exception as e:
        logger.error(f"Failed to load portfolio: {str(e)}")
        raise


if __name__ == "__main__":
    csv_path = "data/portfolio.csv"
    
    if not Path(csv_path).exists():
        logger.error(f"Portfolio CSV not found at {csv_path}")
        sys.exit(1)
    
    try:
        count = load_portfolio_from_csv(csv_path)
        logger.info(f"✓ Successfully initialized portfolio database with {count} entries")
    except Exception as e:
        logger.error(f"✗ Initialization failed: {str(e)}")
        sys.exit(1)