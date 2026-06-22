"""
Agent Routes — Decentralized pipelines for sidebar agents.

GET  /api/agents/status
POST /api/agents/intelligence/run
POST /api/agents/rationalization/run
"""
import logging

from fastapi import APIRouter, HTTPException

from src.server.models.schemas import AgentRunResponse, AgentsStatusResponse
from src.server.models.database import get_database
from src.server.services.agent_orchestrator import get_agent_orchestrator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agents", tags=["Agents"])


@router.get("/status", response_model=AgentsStatusResponse)
async def get_agents_status():
    """Status for Discovery, Intelligence, and Rationalization agents."""
    orchestrator = get_agent_orchestrator(get_database())
    return AgentsStatusResponse(**orchestrator.get_status())


@router.post("/intelligence/run", response_model=AgentRunResponse)
async def run_intelligence_agent():
    """Start BI Intelligence pipeline (KPI clustering, complexity) in background."""
    orchestrator = get_agent_orchestrator(get_database())
    started = orchestrator.run_intelligence_background()
    if not started:
        status = orchestrator.get_status()
        if status["discovery"]["workbook_count"] == 0:
            raise HTTPException(status_code=400, detail="No workbooks in portfolio. Upload files first.")
        if status["intelligence"]["status"] == "running":
            return AgentRunResponse(
                agent="intelligence",
                status="running",
                message="Intelligence analysis is already running.",
            )
        raise HTTPException(status_code=409, detail="Could not start intelligence agent.")
    return AgentRunResponse(
        agent="intelligence",
        status="running",
        message="Intelligence analysis started. KPI clustering and complexity scoring in progress.",
    )


@router.post("/rationalization/run", response_model=AgentRunResponse)
async def run_rationalization_agent():
    """Start BI Rationalization pipeline (risks, overlap, recommendations) in background."""
    orchestrator = get_agent_orchestrator(get_database())
    started = orchestrator.run_rationalization_background()
    if not started:
        status = orchestrator.get_status()
        if status["discovery"]["workbook_count"] == 0:
            raise HTTPException(status_code=400, detail="No workbooks in portfolio. Upload files first.")
        if status["rationalization"]["status"] == "running":
            return AgentRunResponse(
                agent="rationalization",
                status="running",
                message="Rationalization is already running.",
            )
        raise HTTPException(status_code=409, detail="Could not start rationalization agent.")
    return AgentRunResponse(
        agent="rationalization",
        status="running",
        message="Rationalization started. Running overlap scoring and recommendations.",
    )
