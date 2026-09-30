import asyncio
import websockets
import json

async def t():
    try:
        async with websockets.connect("ws://127.0.0.1:9000/ws/test", open_timeout=5) as ws:
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            print("WS OK. First msg:", msg)
    except Exception as e:
        print(f"WS Error: {type(e).__name__}: {e}")

asyncio.run(t())