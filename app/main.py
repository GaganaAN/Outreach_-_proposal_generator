"""
Main FastAPI application for Cold Email Generator
"""
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from pathlib import Path
from app.config import get_settings
from app.api.routes import router
from app.api.admin_routes import router as admin_router
from app.api.email_routes import router as email_router  # NEW
from app.database import init_db

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

settings = get_settings()

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Automated cold email generator using LLM and RAG",
    docs_url="/docs",
    redoc_url="/redoc"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc) if settings.DEBUG else "An unexpected error occurred"
        }
    )


@app.on_event("startup")
async def startup_event():
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    try:
        # NEW: init relational DB
        init_db()
        logger.info("✓ Database initialized")

        from app.core.llm_client import get_llm_client
        from app.core.vector_store import get_vector_store

        llm_client = get_llm_client()
        vector_store = get_vector_store(
            persist_dir=settings.CHROMA_PERSIST_DIR,
            collection_name=settings.COLLECTION_NAME,
            embedding_model=settings.EMBEDDING_MODEL
        )

        logger.info("✓ LLM client initialized")
        logger.info("✓ Vector store initialized")
        logger.info(f"✓ Portfolio documents: {vector_store.count_documents()}")
        logger.info(f"Application ready at http://0.0.0.0:{settings.PORT}")

    except Exception as e:
        logger.error(f"Failed to initialize services: {str(e)}")
        raise


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down application")


# ── Routers ────────────────────────────────────────────────────────────────────
app.include_router(router,       prefix="/api",       tags=["Cold Email Generator"])
app.include_router(admin_router, prefix="/api/admin", tags=["Admin"])
app.include_router(email_router, prefix="/api/admin", tags=["Email Tracking"])


# ── Pages ──────────────────────────────────────────────────────────────────────
@app.get("/")
async def root():
    """Serve main UI"""
    html_path = Path(__file__).parent.parent / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
    return {"app": settings.APP_NAME, "admin": "/admin", "docs": "/docs"}


# /admin redirects to / — portfolio manager is now part of the unified UI
@app.get("/admin")
async def admin_panel():
    """Redirect to unified app (portfolio manager lives in the sidebar)"""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.PORT,
        reload=settings.DEBUG
    )