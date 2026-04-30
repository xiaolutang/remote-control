# Remote Control

A remote terminal control system that lets you access and manage CLI sessions from your phone or desktop. Built with Flutter, FastAPI, and Python.

## Features

- **Flutter Client** -- cross-platform terminal workspace with session management (Android, iOS, macOS, Windows, Linux)
- **FastAPI Server** -- authentication, device management, terminal routing, WebSocket relay
- **Python Agent** -- local PTY management, command execution, WebSocket communication
- **Desktop Agent Lifecycle** -- the desktop client can automatically manage a local Agent process
- **Terminal State Sync** -- exit, restore, and reconnect with consistent terminal state
- **Docker Deployment** -- containerized server and agent with one-command startup
- **End-to-End Encryption** -- RSA + AES encryption for terminal data in transit

## Architecture

```text
┌─────────────┐     WebSocket      ┌─────────────┐     WebSocket      ┌─────────────┐
│   Flutter   │◄──────────────────►│   FastAPI   │◄──────────────────►│   Python    │
│   Client    │                    │   Server    │                    │   Agent     │
│  Mobile/Desktop                 │  + Redis    │                    │  + PTY      │
└─────────────┘                    └─────────────┘                    └─────────────┘
```

The Flutter Client connects to the FastAPI Server over WebSocket. The Server authenticates the client, manages sessions via Redis, and relays terminal I/O to the Python Agent running on the target machine. Each Agent manages a local PTY process and streams input/output back through the Server.

## Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) with Docker Compose (v2) and Buildx
- A terminal / command line

### 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set the required values:

```bash
# Generate a random secret:
openssl rand -hex 32
```

Set `JWT_SECRET` and `REDIS_PASSWORD` to unique, strong values.

### 2. Build and start the server

```bash
./deploy/deploy.sh --dev
```

This builds Docker images and starts the self-contained dev stack (Server + Redis, no Traefik needed). When ready, you will see:

```text
==> Service is ready!
  HTTP API:     http://localhost:8880/
  WebSocket:    ws://localhost:8880
  Health check: http://localhost:8880/health
```

Verify the health check:

```bash
curl http://localhost:8880/health
```

### 3. Create a user account

```bash
curl -X POST http://localhost:8880/api/register \
  -H "Content-Type: application/json" \
  -d '{"username": "myuser", "password": "mypassword"}'
```

### 4. Run the client

```bash
cd client
flutter pub get
flutter run -d macos    # or: flutter run -d windows, flutter run -d linux
```

In the client, select **Direct** connection mode, enter the server IP (e.g. `localhost`) and port (`8880`), then log in with the account you created.

### 5. Connect an agent (optional for desktop)

For desktop clients, the app manages a local Agent automatically. For remote machines, run the Agent standalone:

```bash
cd agent
pip install -r requirements.txt
python -m app.cli login --server http://YOUR_SERVER_IP:8880
python -m app.cli run
```

See [agent/README.md](agent/README.md) for full Agent documentation.

## Project Structure

```text
remote-control/
├── deploy/                     # Docker and deployment
│   ├── docker-compose.dev.yml  # Self-contained dev stack
│   ├── docker-compose.yml      # Production stack (Traefik gateway)
│   ├── server.Dockerfile       # Server multi-stage build
│   ├── agent.Dockerfile        # Agent multi-stage build
│   ├── build.sh                # Build images
│   └── deploy.sh               # Deploy entry point
├── server/                     # FastAPI backend
│   ├── app/                    # Application code
│   └── tests/                  # Server tests
├── agent/                      # Terminal agent
│   ├── app/                    # Agent code
│   └── tests/                  # Agent tests
├── client/                     # Flutter client
│   ├── lib/                    # Dart source
│   └── test/                   # Client tests
├── .env.example                # Environment variable template
└── CLAUDE.md                   # Project conventions (internal)
```

## Configuration

All configuration is handled through environment variables. Copy `.env.example` to `.env` and fill in the values:

| Variable | Required | Description |
|----------|----------|-------------|
| `JWT_SECRET` | Yes | JWT signing secret. Generate with `openssl rand -hex 32` |
| `REDIS_PASSWORD` | Yes | Redis password |
| `LLM_API_KEY` | No | LLM API key (required for Agent AI features) |
| `LLM_BASE_URL` | No | LLM API base URL (OpenAI-compatible) |
| `LLM_MODEL` | No | LLM model name |
| `CORS_ORIGINS` | No | Allowed CORS origins (comma-separated) |
| `RC_DIRECT_PORT` | No | Server port in dev mode (default: `8880`) |
| `LOG_LEVEL` | No | Log level (default: `INFO`) |
| `JWT_EXPIRY_HOURS` | No | JWT expiry in hours (default: `168` = 7 days) |

For Agent standalone deployment (Docker):

| Variable | Description |
|----------|-------------|
| `AGENT_USERNAME` | Agent login username |
| `AGENT_PASSWORD` | Agent login password |

## Development Guide

### Running tests

```bash
# Server tests
cd server
pytest tests/ -v

# Agent tests
cd agent
pytest tests/ -v

# Client tests
cd client
flutter test
```

### Dev compose (manual)

If you prefer to run Docker commands directly:

```bash
# Build images
./deploy/build.sh

# Start dev stack
docker compose --env-file .env -f deploy/docker-compose.dev.yml up -d

# View logs
docker compose -f deploy/docker-compose.dev.yml logs -f

# Stop
docker compose -f deploy/docker-compose.dev.yml down
```

### Running standalone Agent in Docker

```bash
docker compose --env-file .env -f deploy/docker-compose.dev.yml \
  --profile standalone-agent up -d agent
```

Make sure `AGENT_USERNAME` and `AGENT_PASSWORD` are set in `.env` with valid credentials.

### Production deployment

Production uses `docker-compose.yml` with a Traefik gateway. See `deploy/docker-compose.yml` for details.

## Tech Stack

- **Client**: Flutter 3.6+, Dart, Provider, xterm
- **Server**: Python 3.11, FastAPI, uvicorn, Redis, SQLite (aiosqlite), httpx
- **Agent**: Python 3.11, Click, websockets, PTY
- **Deploy**: Docker, Docker Compose, Traefik (production)

## Security

- Always use HTTPS/WSS in production (via a reverse proxy or gateway)
- Set `JWT_SECRET` to a strong random value -- never use the default
- Restrict access via firewall or network policies
- Do not expose development configurations to the public internet
- See [SECURITY.md](SECURITY.md) for vulnerability reporting

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, code style, and PR process.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
