import logging
from pathlib import Path
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 加载 backend/.env 到 os.environ，确保所有模块（尤其是 agents/llms/base.py）都能读取
load_dotenv(Path(__file__).parent / ".env")

from core.config import get_settings
from core.database import connect_db, close_db_connection
from api.v1.router import router as api_v1_router
from scheduler.jobs import start_scheduler, stop_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting InsightPulse API...")
    await connect_db()
    logger.info("SQLite connected.")
    start_scheduler()
    yield
    stop_scheduler()
    await close_db_connection()
    logger.info("InsightPulse API shut down.")


settings = get_settings()

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    description="AI News Intelligence - RSS Crawler API",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_v1_router)


@app.get("/", tags=["Health"])
async def root():
    return {"message": "InsightPulse API is running", "version": settings.VERSION}


@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "healthy", "version": settings.VERSION}
