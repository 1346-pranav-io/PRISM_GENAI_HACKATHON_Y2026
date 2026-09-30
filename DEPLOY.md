# Deploying

Supported: **Render**, **Railway** (Procfile/Nixpacks), any **Docker** host (Fly.io, Cloud Run, etc.).
**Not suitable: Vercel serverless** (no long-lived WebSockets; in-memory state is lost between invocations).

## Start command (from repo root, no `pip install .` needed)
```
uvicorn src.agent_runtime.server.app:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --forwarded-allow-ips="*"
```
**Run exactly ONE worker/instance.** All session state is in-memory; multiple workers or replicas would split sessions.

## Environment variables
- `PORT` - set by the host (default 8000).
- `AGENT_LLM_LATENCY_SECONDS` - optional; mock LLM reasoning delay (default `0.05`). Set to `2` for a hand-typed interruption demo.
- `OPENAI_API_KEY`, `GEMINI_API_KEY` - optional; read only by optional providers. The default server uses the built-in deterministic MockLLMProvider and needs no keys.

## Endpoints
- Health check: `GET /api/v1/health` (readiness: `/api/v1/health/ready`)
- REST: `/api/v1/sessions/{id}/init|message|state|trace`
- WebSocket: `wss://<host>/ws/{session_id}` - send `{"text": "..."}`

## Render
1. Push the repo to GitHub.
2. Render dashboard -> New -> Blueprint -> select repo (uses `render.yaml`). Keep instance count at 1.

## Railway
```
npm i -g @railway/cli
railway login
railway init
railway up
railway domain
```
Railway uses the `Procfile` and `.python-version`. Keep replicas at 1.

Render's free plan sleeps after inactivity; the first request after a sleep can take ~1 minute. Open `/api/v1/health` a few minutes before a demo.

## Verify a deployment
```
python scripts/demo_client.py https://<your-host>
```
Exit code 0 = health/readiness, correction flow, and two-session isolation all verified over the public URL (uses `wss://` automatically for https).

## Docker
```
docker build -t realtime-agent .
docker run -p 8000:8000 -e PORT=8000 realtime-agent
```
