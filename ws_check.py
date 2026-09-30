import asyncio, json, sys
sys.path.insert(0, "src")

import websockets

async def t():
    uri = "ws://127.0.0.1:8000/ws/test_s01"
    try:
        async with websockets.connect(uri, open_timeout=5) as ws:
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            print("WS connected. First msg:", msg)

            await ws.send(json.dumps({"type": "user_text", "text": "hello"}))
            r = await asyncio.wait_for(ws.recv(), timeout=10)
            print("Agent response:", r)
    except Exception as e:
        print("WS Error:", type(e).__name__, str(e))

asyncio.run(t())
