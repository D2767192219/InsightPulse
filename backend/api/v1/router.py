from fastapi import APIRouter
from api.v1 import feeds, articles, reports, signals

router = APIRouter(prefix="/api/v1")
router.include_router(feeds.router)
router.include_router(articles.router)
router.include_router(reports.router)
router.include_router(signals.router)
