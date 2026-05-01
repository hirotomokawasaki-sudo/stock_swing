#!/usr/bin/env python3
"""WebSocket server for real-time console updates."""

import asyncio
import json
import os
import websockets
from pathlib import Path
import sys

# Add project root to path
ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT))

from console.services.dashboard_service import DashboardService

# Connected clients
clients = set()

# Dashboard service
dashboard = DashboardService(PROJECT_ROOT)

HOST = os.environ.get("CONSOLE_WS_HOST", "127.0.0.1")
PORT = int(os.environ.get("CONSOLE_WS_PORT", "3334"))


async def register(websocket):
    """Register new client."""
    clients.add(websocket)
    print(f"Client connected. Total clients: {len(clients)}")


async def unregister(websocket):
    """Unregister client."""
    clients.remove(websocket)
    print(f"Client disconnected. Total clients: {len(clients)}")


async def broadcast_update():
    """Broadcast dashboard update to all clients."""
    if not clients:
        return
    
    try:
        # Get minimal update data
        trading = dashboard.get_trading()
        positions = dashboard.get_positions(trading=trading)
        
        update = {
            "type": "update",
            "timestamp": trading.get("time"),
            "data": {
                "equity": positions.get("summary", {}).get("gross_exposure", 0),
                "unrealized_pnl": positions.get("summary", {}).get("unrealized_pnl", 0),
                "position_count": positions.get("count", 0),
                "summary": trading.get("summary", {})
            }
        }
        
        message = json.dumps(update)
        
        # Send to all clients
        await asyncio.gather(
            *[client.send(message) for client in clients],
            return_exceptions=True
        )
    except Exception as e:
        print(f"Broadcast error: {e}")


async def handler(websocket, path):
    """Handle WebSocket connection."""
    await register(websocket)
    
    try:
        # Send initial data
        trading = dashboard.get_trading()
        positions = dashboard.get_positions(trading=trading)
        
        initial_data = {
            "type": "initial",
            "data": {
                "trading": trading,
                "positions": positions
            }
        }
        
        await websocket.send(json.dumps(initial_data))
        
        # Keep connection alive
        async for message in websocket:
            # Echo heartbeat
            if message == "ping":
                await websocket.send("pong")
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        await unregister(websocket)


async def periodic_updates():
    """Send periodic updates to all clients."""
    while True:
        await asyncio.sleep(30)  # Update every 30 seconds
        await broadcast_update()


async def main():
    """Start WebSocket server."""
    await websockets.serve(handler, HOST, PORT)
    print(f"✅ WebSocket server started on ws://{HOST}:{PORT}")

    # Start periodic updates
    asyncio.create_task(periodic_updates())

    # Keep running
    await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
