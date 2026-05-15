# Massive WebSocket Implementation Guide

## Overview

This guide documents the correct WebSocket configuration for the Business plan contract with Massive (formerly Polygon.io).

**Status**: 📝 Documentation only - WebSocket client not yet implemented

## Configuration

### Environment Variables

Add to `.env`:
```bash
# Massive WebSocket Configuration (Business Plan)
MASSIVE_WS_URL=wss://nasdaq-basic-business.massive.com/stocks
MASSIVE_WS_AUTH_TOKEN=jWjKRcHk7x8_egXHGCGrbWnS67dPgWtp
```

### WebSocket Connection Flow

#### 1. Connect
```bash
wscat -c wss://nasdaq-basic-business.massive.com/stocks
```

#### 2. Authenticate
```json
{"action":"auth", "params":"jWjKRcHk7x8_egXHGCGrbWnS67dPgWtp"}
```

Expected response:
```json
{"status":"auth_success"}
```

#### 3. Subscribe to Symbols
```json
{"action":"subscribe", "params":"AM.AAPL,AM.MSFT,AM.NVDA"}
```

Expected response:
```json
{"status":"success", "message":"subscribed to AM.AAPL,AM.MSFT,AM.NVDA"}
```

#### 4. Receive Real-time Data

Example 1-minute aggregate bar:
```json
{
  "ev": "AM",
  "sym": "AAPL",
  "v": 123456,
  "av": 789012,
  "op": 150.25,
  "vw": 150.30,
  "o": 150.20,
  "c": 150.35,
  "h": 150.40,
  "l": 150.15,
  "a": 150.32,
  "s": 1715786400000,
  "e": 1715786459999
}
```

Field meanings:
- `ev`: Event type ("AM" = 1-minute aggregate)
- `sym`: Symbol
- `v`: Volume
- `av`: Accumulated volume
- `op`: Open price
- `vw`: VWAP
- `o`: Open
- `c`: Close
- `h`: High
- `l`: Low
- `a`: Average
- `s`: Start timestamp (milliseconds)
- `e`: End timestamp (milliseconds)

## Implementation Plan

### Phase 1: Basic WebSocket Client (Not Started)

Create `src/stock_swing/sources/massive_websocket_client.py`:

```python
import asyncio
import json
import os
from typing import Optional, Callable
import websockets
import logging

logger = logging.getLogger(__name__)


class MassiveWebSocketClient:
    """
    WebSocket client for Massive real-time market data.
    
    Usage:
        async def on_message(data):
            print(f"Received: {data}")
        
        client = MassiveWebSocketClient(on_message=on_message)
        await client.connect()
        await client.subscribe(["AAPL", "MSFT"])
        await client.run()
    """
    
    def __init__(
        self,
        on_message: Callable,
        ws_url: Optional[str] = None,
        auth_token: Optional[str] = None
    ):
        self.ws_url = ws_url or os.environ.get(
            "MASSIVE_WS_URL",
            "wss://nasdaq-basic-business.massive.com/stocks"
        )
        self.auth_token = auth_token or os.environ.get("MASSIVE_WS_AUTH_TOKEN")
        self.on_message = on_message
        self.websocket = None
    
    async def connect(self):
        """Connect to WebSocket and authenticate."""
        logger.info(f"Connecting to {self.ws_url}")
        self.websocket = await websockets.connect(self.ws_url)
        
        # Authenticate
        auth_msg = {"action": "auth", "params": self.auth_token}
        await self.websocket.send(json.dumps(auth_msg))
        
        # Wait for auth response
        response = await self.websocket.recv()
        logger.info(f"Auth response: {response}")
    
    async def subscribe(self, symbols: list[str]):
        """
        Subscribe to real-time 1-minute aggregate bars.
        
        Args:
            symbols: List of ticker symbols (e.g., ["AAPL", "MSFT"])
        """
        # Format: AM.SYMBOL for 1-minute aggregates
        params = ",".join([f"AM.{sym}" for sym in symbols])
        sub_msg = {"action": "subscribe", "params": params}
        
        logger.info(f"Subscribing to: {params}")
        await self.websocket.send(json.dumps(sub_msg))
        
        # Wait for subscription response
        response = await self.websocket.recv()
        logger.info(f"Subscribe response: {response}")
    
    async def run(self):
        """Run the WebSocket message loop."""
        try:
            async for message in self.websocket:
                data = json.loads(message)
                await self.on_message(data)
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket connection closed")
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
    
    async def close(self):
        """Close the WebSocket connection."""
        if self.websocket:
            await self.websocket.close()
```

### Phase 2: Console Integration (Not Started)

Integrate WebSocket into console for live price updates:

1. Add WebSocket connection management to console backend
2. Update frontend to display real-time prices
3. Update unrealized P&L calculations with live data

### Phase 3: Trading Integration (Future)

Use real-time data for:
- Live position monitoring
- Intraday entry/exit signals
- Real-time alert triggers

## Testing

### Manual Test with wscat

```bash
# Install wscat
npm install -g wscat

# Connect
wscat -c wss://nasdaq-basic-business.massive.com/stocks

# After connection, send auth:
{"action":"auth", "params":"jWjKRcHk7x8_egXHGCGrbWnS67dPgWtp"}

# Subscribe to AAPL and MSFT 1-minute bars:
{"action":"subscribe", "params":"AM.AAPL,AM.MSFT"}

# Watch for incoming messages
# Press Ctrl+C to exit
```

### Automated Test Script

Create `scripts/test_massive_websocket.py`:

```python
import asyncio
from src.stock_swing.sources.massive_websocket_client import MassiveWebSocketClient


async def handle_message(data):
    """Handle incoming WebSocket messages."""
    print(f"Received: {data}")


async def main():
    client = MassiveWebSocketClient(on_message=handle_message)
    await client.connect()
    await client.subscribe(["AAPL", "MSFT", "NVDA"])
    await client.run()


if __name__ == "__main__":
    asyncio.run(main())
```

## Data Format Reference

### Aggregate Minute Bar (AM)

```json
{
  "ev": "AM",           // Event type
  "sym": "AAPL",        // Symbol
  "v": 123456,          // Volume
  "av": 789012,         // Accumulated volume
  "op": 150.25,         // Official open
  "vw": 150.30,         // VWAP
  "o": 150.20,          // Bar open
  "c": 150.35,          // Bar close
  "h": 150.40,          // Bar high
  "l": 150.15,          // Bar low
  "a": 150.32,          // Bar average
  "s": 1715786400000,   // Start timestamp (ms)
  "e": 1715786459999    // End timestamp (ms)
}
```

### Trade (T)

```json
{
  "ev": "T",            // Event type
  "sym": "AAPL",        // Symbol
  "x": 4,               // Exchange ID
  "p": 150.25,          // Price
  "s": 100,             // Size
  "t": 1715786401234    // Timestamp (ms)
}
```

### Quote (Q)

```json
{
  "ev": "Q",            // Event type
  "sym": "AAPL",        // Symbol
  "bx": 4,              // Bid exchange
  "bp": 150.24,         // Bid price
  "bs": 200,            // Bid size
  "ax": 12,             // Ask exchange
  "ap": 150.26,         // Ask price
  "as": 300,            // Ask size
  "t": 1715786401234    // Timestamp (ms)
}
```

## Important Notes

⚠️ **Contract-Specific Endpoints**
- The default documentation shows `wss://socket.massive.com/stocks`
- **This is WRONG for Business plan accounts**
- Always use `wss://nasdaq-basic-business.massive.com/stocks`

⚠️ **Authentication**
- Business plan uses token-based auth via WebSocket messages
- **NOT** API key in HTTP headers like REST API
- Auth message: `{"action":"auth", "params":"<token>"}`

⚠️ **Symbol Format**
- Prefix with event type: `AM.AAPL` for 1-minute aggregates
- Other formats: `T.AAPL` (trades), `Q.AAPL` (quotes)

## References

- [Massive WebSocket Docs](https://massive.com/docs/websocket/overview) (⚠️ Generic - use config above)
- [Python WebSockets Library](https://websockets.readthedocs.io/)
- Contract-specific config: See `.env` and this document

## Status Tracking

- [x] Document correct WebSocket configuration
- [x] Add environment variables to `.env`
- [ ] Implement `MassiveWebSocketClient`
- [ ] Create test script
- [ ] Manual testing with wscat
- [ ] Automated testing
- [ ] Console integration
- [ ] Trading system integration
