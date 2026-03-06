"""
Pydantic models for request/response validation
"""
from pydantic import BaseModel, HttpUrl, Field
from typing import List, Optional, Dict


class JobExtractionRequest(BaseModel):
    """Request model for job extraction"""
    job_url: HttpUrl = Field(..., description="URL of the job posting page")
    
    class Config:
        json_schema_extra = {
            "example": {
                "job_url": "https://jobs.nike.com/job/R-12345"
            }
        }


class JobDetails(BaseModel):
    """Structured job information extracted by LLM"""
    job_role: str = Field(..., description="Job title/role")
    skills: List[str] = Field(..., description="Required technical skills")
    description: str = Field(..., description="Job description summary")
    experience_level: Optional[str] = Field(None, description="Experience level required")
    location: Optional[str] = Field(None, description="Job location")


class PortfolioMatch(BaseModel):
    """Portfolio entry matched to a skill"""
    skill: str
    portfolio_link: str
    projects: List[str]
    relevance_score: float = Field(..., ge=0.0, le=1.0)


class EmailGenerationRequest(BaseModel):
    """Request model for email generation"""
    job_url: HttpUrl = Field(..., description="URL of the job posting")
    
    class Config:
        json_schema_extra = {
            "example": {
                "job_url": "https://jobs.nike.com/job/R-12345"
            }
        }


class EmailGenerationResponse(BaseModel):
    """Response model for generated email"""
    email_subject: str
    email_body: str
    job_details: JobDetails
    matched_portfolios: List[PortfolioMatch]
    processing_time: float = Field(..., description="Processing time in seconds")


class JobExtractionResponse(BaseModel):
    """Response model for job extraction only"""
    job_details: JobDetails
    raw_text_length: int
    processing_time: float


class PortfolioUploadRequest(BaseModel):
    """Request model for uploading portfolio data"""
    skill: str
    portfolio_link: HttpUrl
    projects: List[str]
    description: Optional[str] = None


class PortfolioSearchRequest(BaseModel):
    """Request model for portfolio search"""
    skills: List[str]
    top_k: int = Field(default=3, ge=1, le=10)


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    app_name: str
    version: str
    llm_status: str
    vectordb_status: str


class ErrorResponse(BaseModel):
    """Error response model"""
    error: str
    detail: Optional[str] = None
    status_code: int