import asyncio
import json
import logging
from fastapi import FastAPI
from fastapi.websockets import WebSocket

logging.basicConfig(level=logging.DEBUG)

app = FastAPI()

@app.websocket("/ws/{session_id}")
async def ws_test(ws: WebSocket, session_id: str):
    print(f"[WS] Endpoint reached! session_id={session_id}")
    await ws.accept()
    await ws.send_json({"event_type": "connected", "session_id": session_id})
    try:
        while True:
            data = await ws.receive_text()
            await ws.send_json({"echo": data})
    except Exception:
        pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=9000, log_level="debug")
