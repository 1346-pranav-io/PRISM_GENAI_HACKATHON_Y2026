import httpx, asyncio

async def t():
    async with httpx.AsyncClient(timeout=10) as c:
        try:
            async with c.connect("ws://127.0.0.1:8000/ws/test_s01") as ws:
                msg = await ws.receive_text()
                print("WS OK:", msg)
        except httpx.ConnectError as e:
            print("ConnectError:", e)
        except Exception as e:
            print("Error type:", type(e).__name__)
            print("Error args:", e.args if hasattr(e, 'args') else str(e))
            # Try to get response details
            if hasattr(e, 'response'):
                print("Response status:", e.response.status_code)
                print("Response body:", e.response.text)

asyncio.run(t())