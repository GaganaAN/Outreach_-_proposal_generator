"""
API routes for Cold Email Generator
"""
import logging
import time
from fastapi import APIRouter, HTTPException, status
from app.api.schemas import (
    EmailGenerationRequest,
    EmailGenerationResponse,
    JobExtractionRequest,
    JobExtractionResponse,
    PortfolioUploadRequest,
    PortfolioSearchRequest,
    HealthResponse,
    ErrorResponse
)
from app.services.job_extractor import get_job_extractor
from app.services.portfolio_matcher import get_portfolio_matcher
from app.services.email_generator import get_email_generator
from app.core.llm_client import get_llm_client
from app.core.vector_store import get_vector_store
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    try:
        settings = get_settings()
        llm_client = get_llm_client()
        vector_store = get_vector_store(
            persist_dir=settings.CHROMA_PERSIST_DIR,
            collection_name=settings.COLLECTION_NAME,
            embedding_model=settings.EMBEDDING_MODEL
        )
        
        llm_healthy = llm_client.check_health()
        vectordb_healthy = vector_store.check_health()
        
        return HealthResponse(
            status="healthy" if (llm_healthy and vectordb_healthy) else "degraded",
            app_name=settings.APP_NAME,
            version=settings.APP_VERSION,
            llm_status="healthy" if llm_healthy else "unhealthy",
            vectordb_status="healthy" if vectordb_healthy else "unhealthy"
        )
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Service unhealthy: {str(e)}"
        )


@router.post("/extract-job", response_model=JobExtractionResponse)
async def extract_job(request: JobExtractionRequest):
    """
    Extract structured job information from a job posting URL
    """
    start_time = time.time()
    
    try:
        logger.info(f"Processing job extraction request: {request.job_url}")
        
        job_extractor = get_job_extractor()
        
        # Process job URL
        result = job_extractor.process_job_url(str(request.job_url))
        
        processing_time = time.time() - start_time
        
        return JobExtractionResponse(
            job_details=result["job_details"],
            raw_text_length=result["raw_text_length"],
            processing_time=round(processing_time, 2)
        )
        
    except Exception as e:
        logger.error(f"Job extraction failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to extract job details: {str(e)}"
        )


@router.post("/generate-email", response_model=EmailGenerationResponse)
async def generate_email(request: EmailGenerationRequest):
    """
    Generate a personalized cold email from a job posting URL
    
    This endpoint performs the complete pipeline:
    1. Scrape and extract job details
    2. Match skills with portfolio
    3. Generate personalized email
    """
    start_time = time.time()
    
    try:
        logger.info(f"Processing email generation request: {request.job_url}")
        
        # Initialize services
        job_extractor = get_job_extractor()
        portfolio_matcher = get_portfolio_matcher()
        email_generator = get_email_generator()
        
        # Step 1: Extract job details
        logger.info("Step 1: Extracting job details")
        job_result = job_extractor.process_job_url(str(request.job_url))
        job_details = job_result["job_details"]
        
        # Step 2: Match skills to portfolio
        logger.info("Step 2: Matching skills to portfolio")
        portfolio_matches = portfolio_matcher.match_skills_to_portfolio(
            skills=job_details.skills,
            top_k=3
        )
        
        # Step 3: Generate email
        logger.info("Step 3: Generating email")
        email_content = email_generator.generate_complete_email(
            job_details=job_details,
            portfolio_matches=portfolio_matches
        )
        
        processing_time = time.time() - start_time
        
        logger.info(f"Email generated successfully in {processing_time:.2f}s")
        
        # NEW: Auto-save to database for tracking
        try:
            from app.database import SessionLocal
            from app.models import Email
            import json
            from urllib.parse import urlparse
            
            # Extract company name from URL
            domain = urlparse(str(request.job_url)).netloc
            company = domain.replace('www.', '').replace('jobs.', '').replace('careers.', '').split('.')[0].capitalize()
            
            # Save to database
            db = SessionLocal()
            try:
                email_record = Email(
                    job_url=str(request.job_url),
                    company_name=company,
                    job_role=job_details.job_role,
                    email_subject=email_content["email_subject"],
                    email_body=email_content["email_body"],
                    skills=json.dumps(job_details.skills),
                    matched_portfolios=json.dumps([m.dict() for m in portfolio_matches]),
                    status="draft"
                )
                db.add(email_record)
                db.commit()
                # Get ID before closing session
                email_id = email_record.id
                logger.info(f"✓ Saved email to history (ID: {email_id})")
            finally:
                db.close()
        except Exception as save_error:
            logger.warning(f"Failed to save email to history: {save_error}")
            # Don't fail the request if saving fails
        
        return EmailGenerationResponse(
            email_subject=email_content["email_subject"],
            email_body=email_content["email_body"],
            job_details=job_details,
            matched_portfolios=portfolio_matches,
            processing_time=round(processing_time, 2)
        )
        
    except Exception as e:
        logger.error(f"Email generation failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate email: {str(e)}"
        )


@router.post("/portfolio/upload", status_code=status.HTTP_201_CREATED)
async def upload_portfolio(request: PortfolioUploadRequest):
    """
    Add a new portfolio entry to the vector store
    """
    try:
        logger.info(f"Uploading portfolio entry for skill: {request.skill}")
        
        portfolio_matcher = get_portfolio_matcher()
        
        doc_id = portfolio_matcher.add_portfolio_entry(
            skill=request.skill,
            portfolio_link=str(request.portfolio_link),
            projects=request.projects,
            description=request.description or ""
        )
        
        return {
            "message": "Portfolio entry added successfully",
            "document_id": doc_id,
            "skill": request.skill
        }
        
    except Exception as e:
        logger.error(f"Portfolio upload failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload portfolio: {str(e)}"
        )


@router.post("/portfolio/search")
async def search_portfolio(request: PortfolioSearchRequest):
    """
    Search for portfolio entries matching given skills
    """
    try:
        logger.info(f"Searching portfolio for skills: {request.skills}")
        
        portfolio_matcher = get_portfolio_matcher()
        
        matches = portfolio_matcher.match_skills_to_portfolio(
            skills=request.skills,
            top_k=request.top_k
        )
        
        return {
            "matches": matches,
            "total_matches": len(matches)
        }
        
    except Exception as e:
        logger.error(f"Portfolio search failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to search portfolio: {str(e)}"
        )


@router.get("/portfolio/stats")
async def portfolio_stats():
    """
    Get statistics about the portfolio database
    """
    try:
        settings = get_settings()
        vector_store = get_vector_store(
            persist_dir=settings.CHROMA_PERSIST_DIR,
            collection_name=settings.COLLECTION_NAME,
            embedding_model=settings.EMBEDDING_MODEL
        )
        doc_count = vector_store.count_documents()
        
        return {
            "total_documents": doc_count,
            "status": "active" if doc_count > 0 else "empty"
        }
        
    except Exception as e:
        logger.error(f"Failed to get portfolio stats: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get stats: {str(e)}"
        )