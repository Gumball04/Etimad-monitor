# Etimad Monitor

## Prerequisites

- Docker Engine (or Docker Desktop)
- Docker Compose plugin (`docker compose`)

## Run the full stack

```bash
docker compose up --build
```

Services:

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- Backend docs: http://localhost:8000/docs
- Postgres: `localhost:5433` (db: `etimad`, user: `postgres`, password: `123`)

The stack is configured for development:

- Frontend uses Vite with live reload.
- Backend runs Uvicorn with `--reload`.
- Backend source and frontend source are mounted into containers.

## Stop services

```bash
docker compose down
```

## Reset all local Docker data (including DB)

```bash
docker compose down -v
```

## Notes

- First build can take longer because Playwright Chromium and Python/Node dependencies are installed.
- If you see Docker socket/daemon errors, start Docker first, then rerun `docker compose up --build`.
