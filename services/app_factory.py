from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from services.app_state import AppState


def create_app(state: AppState) -> FastAPI:
    """
    Create and configure the FastAPI application instance.

    This factory pattern allows for:
    - Dependency injection of application state
    - Easier testing with different configurations
    - Clean separation of concerns
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        """Application lifespan handler for startup/shutdown."""
        # Startup
        print(f"[STARTUP] ClaudeProxy v3 starting...")
        print(f"[STARTUP] Debug mode: {state.debug_mode}")
        print(f"[STARTUP] Queue mode: {state.queue_mode}")

        # Store state in app for access by routes
        app.state.app_state = state

        yield

        # Shutdown
        print(f"[SHUTDOWN] ClaudeProxy v3 shutting down...")
        print(f"[SHUTDOWN] Total requests: {state.stats['total_requests']}")

    app = FastAPI(
        title="Claude Proxy v3 - Optimized",
        description="eBay arbitrage analyzer with async image fetching and smart caching",
        lifespan=lifespan,
    )

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return Response(status_code=204)

    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {
            "status": "healthy",
            "enabled": state.enabled,
            "total_requests": state.stats["total_requests"],
        }

    # TODO: Register routers here
    # app.include_router(analysis_router)
    # app.include_router(sellers_router)
    # etc.

    return app


# Convenience function for getting state from request
def get_app_state(app: FastAPI) -> AppState:
    """Get the AppState instance from the FastAPI app."""
    return app.state.app_state
