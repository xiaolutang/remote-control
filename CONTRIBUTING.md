# Contributing to Remote Control

Thank you for your interest in contributing! This guide covers the development environment setup, code style, and PR process.

## Development Environment

### Prerequisites

- **Python 3.11+** for Server and Agent development
- **Flutter 3.6+** (Dart SDK 3.6+) for Client development
- **Docker** with Docker Compose (v2) and Buildx
- **Redis** (provided via Docker in dev mode)

### Setup

1. Fork and clone the repository.

2. Copy the environment template and configure:

   ```bash
   cp .env.example .env
   ```

   Edit `.env` and set `JWT_SECRET` and `REDIS_PASSWORD` (generate with `openssl rand -hex 32`).

3. Build and start the dev server:

   ```bash
   ./deploy/deploy.sh --dev
   ```

   This starts Server + Redis on port 8880 without requiring a Traefik gateway.

4. Verify the server is running:

   ```bash
   curl http://localhost:8880/health
   ```

### Running the dev compose manually

```bash
# Build images
./deploy/build.sh

# Start
docker compose --env-file .env -f deploy/docker-compose.dev.yml up -d

# View logs
docker compose -f deploy/docker-compose.dev.yml logs -f server

# Stop
docker compose -f deploy/docker-compose.dev.yml down
```

### Running tests

```bash
# Server tests
cd server
pip install -r requirements.txt
pytest tests/ -v

# Agent tests
cd agent
pip install -r requirements.txt
pytest tests/ -v

# Client tests
cd client
flutter pub get
flutter test
```

## Code Style

### Python (Server / Agent)

- Follow [PEP 8](https://peps.python.org/pep-0008/) with a line length of 120 characters.
- Use type hints for function signatures.
- Write docstrings for public functions and classes.
- Use `async/await` for all I/O-bound operations.
- Sort imports: standard library, third-party, local.

### Dart (Client)

- Follow [Effective Dart](https://dart.dev/guides/language/effective-dart) conventions.
- Run `flutter analyze` before submitting -- no warnings or errors.
- Use `provider` for state management.
- Keep widget files focused; split large widgets into smaller, testable units.

### General

- Keep commits atomic and focused on a single change.
- Write clear, descriptive commit messages.
- Update tests when changing behavior.
- Do not commit hardcoded credentials, API keys, or internal domain names.

## PR Process

1. **Create a branch** from `main`:

   ```bash
   git checkout -b feature/my-change main
   ```

2. **Make your changes** and ensure all tests pass.

3. **Write tests** for new functionality. Bug fixes should include a regression test.

4. **Update documentation** if your change affects behavior, configuration, or the API.

5. **Submit a pull request** against the `main` branch with:
   - A clear title summarizing the change
   - A description of what changed and why
   - Any relevant issue references

6. **Code review**: at least one approval is required before merge. Address all review feedback.

7. **CI must pass**: all tests green, no analysis warnings.

### PR Checklist

- [ ] Changes are focused and atomic
- [ ] All tests pass (`pytest`, `flutter test`)
- [ ] No hardcoded credentials or internal references
- [ ] Documentation updated if needed
- [ ] Commit messages are clear and descriptive

## Reporting Issues

- Use [GitHub Issues](../../issues) for bug reports and feature requests.
- Include steps to reproduce, expected behavior, and actual behavior.
- Specify your environment (OS, Docker version, Flutter version, etc.).

## Questions?

Feel free to open a discussion or an issue. We are happy to help.
