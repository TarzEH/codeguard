# Contributing to CodeGuard

Thanks for your interest in contributing! Here's how to get started.

## Prerequisites

- **Docker** and **Docker Compose** (v2)
- **Python 3.11+**
- **shellcheck**

## Local development setup

```bash
# Clone the repo
git clone https://github.com/TarzEH/codeguard.git
cd codeguard

# Start the full cluster
docker compose up -d --build

# Verify the cluster is healthy
curl -sf http://127.0.0.1:80/health
```

## Running tests

```bash
# Unit tests
pip install -r requirements-dev.txt
pytest -v

# Shell linting
shellcheck -S warning install.sh src/cli/*.sh scripts/*.sh

# Integration tests (requires a running cluster)
./tests/integration/failover_test.sh
```

## Pull request conventions

1. **Branch from `main`** — use a descriptive branch name (e.g. `fix/cache-ttl`, `feat/sbom-export`).
2. **Descriptive title** — keep it under 70 characters.
3. **Reference an issue** if one exists (e.g. `Fixes #42`).
4. **All checks must pass** — `pytest`, `shellcheck`, and the integration suite run automatically in CI.
5. **No secrets in the diff** — run `git grep --cached -E 'sk-|ghp_|AIza'` before pushing.

## Commit messages

Use conventional-commit style (`feat:`, `fix:`, `chore:`, `docs:`, `test:`). Keep the first line under 72 characters.

## Questions?

Open a discussion or an issue — we're happy to help.
