"""
WebSocket Routes and Real-time Dashboard

Handles WebSocket connections for real-time listing updates
and serves the ShadowSnipe Live dashboard.

Extracted from main.py for better organization.
"""

import json
import logging
from datetime import datetime
from typing import List
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)

router = APIRouter()


class ConnectionManager:
    """Manage WebSocket connections for real-time updates"""

    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"[WS] Client connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"[WS] Client disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """Send message to all connected clients"""
        if not self.active_connections:
            return

        message_json = json.dumps(message)
        disconnected = []

        for connection in self.active_connections:
            try:
                await connection.send_text(message_json)
            except Exception as e:
                logger.debug(f"[WS] Send error: {e}")
                disconnected.append(connection)

        # Clean up disconnected
        for conn in disconnected:
            self.disconnect(conn)


# Global connection manager
ws_manager = ConnectionManager()


def get_ws_manager() -> ConnectionManager:
    """Get the global WebSocket manager instance"""
    return ws_manager


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time listing updates"""
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep connection alive, receive any client messages
            data = await websocket.receive_text()
            logger.debug(f"[WS] Received: {data}")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.debug(f"[WS] Error: {e}")
        ws_manager.disconnect(websocket)


# Load the HTML template
_LIVE_DASHBOARD_HTML = None

def _load_live_dashboard_html() -> str:
    """Load the live dashboard HTML template"""
    global _LIVE_DASHBOARD_HTML
    if _LIVE_DASHBOARD_HTML is None:
        template_path = Path(__file__).parent.parent / "templates" / "live_dashboard.html"
        if template_path.exists():
            with open(template_path, 'r', encoding='utf-8') as f:
                _LIVE_DASHBOARD_HTML = f.read()
        else:
            _LIVE_DASHBOARD_HTML = "<html><body><h1>Live Dashboard Template Not Found</h1></body></html>"
    return _LIVE_DASHBOARD_HTML


@router.get("/live")
async def live_dashboard():
    """Serve the live dashboard HTML with TTS for BUY alerts"""
    html_content = _load_live_dashboard_html()
    return HTMLResponse(content=html_content)


async def broadcast_new_listing(listing: dict, analysis: dict = None):
    """Broadcast a new listing to all connected dashboard clients"""
    message = {
        "type": "new_listing",
        "timestamp": datetime.now().isoformat(),
        "listing": listing,
        "analysis": analysis,
    }
    logger.info(f"[WS] Broadcasting: title='{listing.get('title', 'MISSING')[:50]}', price={listing.get('price')}, rec={analysis.get('Recommendation') if analysis else 'N/A'}")
    await ws_manager.broadcast(message)


# Configuration function for main.py to inject dependencies if needed
def configure_websocket(**kwargs):
    """Configure websocket module with dependencies from main"""
    pass  # Currently no configuration needed
