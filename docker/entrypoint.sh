#!/usr/bin/env bash
set -euo pipefail

poetry run alembic upgrade head
exec poetry run python -m app.main
