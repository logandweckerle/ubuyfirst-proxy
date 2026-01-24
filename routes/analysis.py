"""
Analysis Route - thin endpoint delegating to pipeline orchestrator.

The /match_mydata endpoint receives eBay listing alerts and delegates
all processing to the pipeline orchestrator.
"""

import logging

from fastapi import APIRouter, Request

from pipeline.orchestrator import run_analysis

logger = logging.getLogger(__name__)

router = APIRouter()


def configure_analysis():
    """No-op for backwards compatibility. Orchestrator is configured separately."""
    pass


@router.post("/match_mydata")
@router.get("/match_mydata")
async def analyze_listing(request: Request):
    """Main analysis endpoint - delegates to pipeline orchestrator."""
    return await run_analysis(request)
