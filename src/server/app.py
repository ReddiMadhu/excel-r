"""
FastAPI Application Factory — Excel Rationalization Server.

Serves 12 REST endpoints mirroring the BI Compass frontend contract
with Excel-specific adaptations.
"""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.server.models.database import get_database

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
# Timing profiler — always INFO; writes to data/output/timing.log
logging.getLogger("timing").setLevel(logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: init DB on startup, cleanup on shutdown."""
    logger.info("Starting Excel Rationalization Server...")

    # Initialize database (creates schema if needed)
    db = get_database()
    logger.info("Database initialized at: %s", db.db_path)

    yield

    # Cleanup
    logger.info("Shutting down Excel Rationalization Server...")
    db.close()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Excel Rationalization Server",
        description=(
            "FastAPI backend for Excel workbook extraction and rationalization. "
            "Mirrors the BI Compass frontend contract with Excel-specific adaptations."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS — wide open for development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register route modules
    from src.server.routes import scans
    from src.server.routes import workbooks
    from src.server.routes import dashboards
    from src.server.routes import calculated_fields
    from src.server.routes import datasources
    from src.server.routes import kpi_clusters
    from src.server.routes import governance
    from src.server.routes import kpi_graph
    from src.server.routes import agents
    from src.server.routes import discovery
    from src.server.routes import data_management

    app.include_router(scans.router)
    app.include_router(workbooks.router)
    app.include_router(dashboards.router)
    app.include_router(calculated_fields.router)
    app.include_router(datasources.router)
    app.include_router(kpi_clusters.router)
    app.include_router(governance.router)
    app.include_router(kpi_graph.router)
    app.include_router(agents.router)
    app.include_router(discovery.router)
    app.include_router(data_management.router)

    # Health check endpoint
    @app.get("/api/health", tags=["Health"])
    async def health_check():
        db = get_database()
        workbook_count = db.query_one("SELECT COUNT(*) as cnt FROM workbooks")
        scan_count = db.query_one("SELECT COUNT(*) as cnt FROM scans")
        return {
            "status": "healthy",
            "database": db.db_path,
            "workbooks": workbook_count["cnt"] if workbook_count else 0,
            "scans": scan_count["cnt"] if scan_count else 0,
        }

    logger.info("FastAPI app created with %d routes", len(app.routes))
    return app
