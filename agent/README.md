# Remote Control Agent

Python CLI agent for Remote Control. Runs on the target machine, manages a local PTY process, and communicates with the Remote Control Server over WebSocket.

## Prerequisites

- Python 3.11+
- A running Remote Control Server (see project root README for setup)

## Installation

```bash
cd agent
pip install -r requirements.txt
```

## Usage

The agent uses a CLI with subcommands. The primary workflow is: **login** once, then **run** anytime.

### Login

Authenticate with the server and save credentials locally:

```bash
python -m app.cli login --server http://YOUR_SERVER_IP:8880
```

You will be prompted for your username and password. Credentials are saved to a local config file for subsequent runs.

### Run

Start the agent using saved credentials:

```bash
python -m app.cli run
```

The agent will:
1. Load saved configuration and tokens
2. Automatically refresh expired tokens (or re-login if credentials are saved)
3. Connect to the server over WebSocket
4. Start a PTY session (default shell: `/bin/bash`)

### Start (one-shot)

Connect with explicit parameters without saving configuration:

```bash
python -m app.cli start --server ws://YOUR_SERVER_IP:8880 --token YOUR_TOKEN
```

### Check Status

View current configuration and connection state:

```bash
python -m app.cli status
```

### Configure

Update saved configuration without starting a connection:

```bash
python -m app.cli configure --server ws://YOUR_SERVER_IP:8880 --username myuser
```

### Logout

Clear saved credentials:

```bash
python -m app.cli logout
```

## CLI Reference

| Command | Description |
|---------|-------------|
| `login` | Authenticate and save credentials |
| `run` | Start agent with saved config (supports auto-login) |
| `start` | Start with explicit parameters (no saved config) |
| `status` | Show connection status and configuration |
| `configure` | Update saved configuration |
| `logout` | Clear saved credentials |

### Global Options

| Option | Default | Description |
|--------|---------|-------------|
| `--server` | (from config) | Server URL (e.g., `ws://host:8880` or `wss://host/rc`) |
| `--token` | (from config) | Authentication token |
| `--command` | `/bin/bash` | Shell command to execute |
| `--shell` | `false` | Start an interactive shell |
| `--reconnect` / `--no-reconnect` | `true` | Auto-reconnect on disconnect |
| `--max-retries` | `60` | Maximum reconnection attempts |
| `--config` | `~/.rc-agent/config.json` | Custom config file path |
| `--version` | | Show version |

## Connecting to a Dev Deployment

When using the self-contained dev compose (`./deploy/deploy.sh --dev`), the server is available at `http://YOUR_SERVER_IP:8880`.

```bash
# Login
python -m app.cli login --server http://localhost:8880

# Run
python -m app.cli run
```

## Running in Docker

The agent can run as a Docker container alongside the server:

```bash
# Set credentials in .env
echo "AGENT_USERNAME=myuser" >> .env
echo "AGENT_PASSWORD=mypassword" >> .env

# Start agent container
docker compose --env-file .env -f deploy/docker-compose.dev.yml \
  --profile standalone-agent up -d agent
```

## Running Tests

```bash
cd agent
pytest tests/ -v
```

## Project Structure

```text
agent/
├── app/
│   ├── cli.py              # CLI entry point and commands
│   ├── main.py             # Module entry point
│   ├── config.py           # Configuration management
│   ├── websocket_client.py # WebSocket client
│   ├── auth_service.py     # Authentication service
│   ├── pty_wrapper.py      # PTY process management
│   ├── crypto.py           # Encryption utilities
│   └── ...
├── tests/                  # Test suite
├── requirements.txt        # Python dependencies
└── pyproject.toml          # Project metadata
```

## Dependencies

- **websockets** -- WebSocket client
- **click** -- CLI framework
- **aiohttp** -- Async HTTP client
- **cryptography** -- Encryption and key management
- **pydantic** -- Data validation
