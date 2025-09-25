# Ben Bot

Personal Telegram assistant with inline admin control, subscription gate, and future-ready sales workflows.

## Highlights
- Owner-locked admin panel to manage subscription requirements and future catalog/orders.
- Inline, button-only navigation for users and administrators (no free-form text needed).
- Membership enforcement layer that checks required channels and can be toggled per demand.
- Modular product, order, and settings models designed for extension.
- Structured logging, async database access, and Docker-first deployment.

## Stack
- Python 3.12, Aiogram 3, asyncio.
- MariaDB via SQLAlchemy 2 + AsyncMy.
- Pydantic Settings for configuration management.
- Alembic for migrations.
- Docker & Docker Compose for local and production parity.

## Quickstart (Docker)
1. Copy environment template and fill in secrets:
   ```bash
   cp .env.example .env
   ```
2. Build and boot the stack (bot + MariaDB):
   ```bash
   docker compose up --build
   ```
3. The entrypoint automatically applies migrations (`alembic upgrade head`) before launching the bot.

## Migrations & Tooling
- Apply migrations manually (outside Docker) with `poetry run alembic upgrade head`.
- Create new revisions via `poetry run alembic revision --autogenerate -m "message"`.
- Run the bot locally with `poetry run python -m app.main` (MariaDB must be available).

## Configuration
Key environment variables (see `.env.example`):
- `BOT_TOKEN`: Telegram bot token from @BotFather.
- `BOT_OWNER_USER_IDS`: Comma-separated Telegram user IDs allowed to access admin features.
- `REQUIRE_SUBSCRIPTION_DEFAULT`: Default toggle for membership enforcement (true/false).
- `REQUIRED_CHANNELS_DEFAULT`: Comma-separated channel usernames to enforce subscription.
- `PAYMENT_PROVIDER_TOKEN`, `PAYMENT_CURRENCY`, `INVOICE_PAYMENT_TIMEOUT_MINUTES`: defaults for payment flows.

## Project Layout
```
app/
  bot/              # Routers, keyboards, middlewares
  core/             # Config and logging utilities
  infrastructure/   # Database models, repositories, sessions
  services/         # Business logic (config, membership, products)
  main.py           # Application entrypoint
alembic/            # Migration environment and versions
```

## Next Steps
- Implement product purchase flow and payment integration via Telegram invoices.
- Build channel management, catalog CRUD, and support modules within the admin panel.
- Extend migrations and services as new features land.
