# Ben Bot

Personal Telegram assistant with inline admin control, subscription gate, and future-ready sales workflows.

## Highlights
- Owner-locked admin panel to manage subscription requirements and future catalog/orders.
- Inline, button-only navigation for users and administrators (no free-form text needed).
- OxaPay crypto checkout with configurable currencies, lifetimes, and automatic status sync.
- Membership enforcement layer that checks required channels and can be toggled per demand.
- Support desk spam guard with configurable rate limits and automatic user notifications on resolution.
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
- `SUPPORT_ANTISPAM_MAX_OPEN_TICKETS`, `SUPPORT_ANTISPAM_MAX_TICKETS_PER_WINDOW`, `SUPPORT_ANTISPAM_WINDOW_MINUTES`, `SUPPORT_ANTISPAM_MIN_REPLY_INTERVAL_SECONDS`: Base anti-spam thresholds for the support desk (also adjustable from the admin panel).
- `PAYMENT_PROVIDER_TOKEN`, `PAYMENT_CURRENCY`, `INVOICE_PAYMENT_TIMEOUT_MINUTES`: defaults for payment flows.
- **OxaPay crypto payments**:
  - `OXAPAY_API_KEY`: Merchant API key from the OxaPay dashboard (required to enable crypto checkout).
  - `OXAPAY_BASE_URL`, `OXAPAY_CHECKOUT_BASE_URL`: API and public checkout URLs (override for sandbox/self-hosting).
  - `OXAPAY_SANDBOX`: Toggle sandbox mode when using test credentials.
  - `OXAPAY_DEFAULT_CURRENCIES`: Comma-separated crypto symbols accepted by default (e.g., `USDT,BTC`).
  - `OXAPAY_INVOICE_LIFETIME_MINUTES`: Default invoice expiration in minutes (15–2880).
  - `OXAPAY_MIXED_PAYMENT`, `OXAPAY_FEE_PAYER`, `OXAPAY_UNDERPAID_COVERAGE`, `OXAPAY_AUTO_WITHDRAWAL`, `OXAPAY_TO_CURRENCY`: Behavioural defaults for invoices and settlements.
  - `OXAPAY_RETURN_URL`, `OXAPAY_CALLBACK_URL`, `OXAPAY_CALLBACK_SECRET`: Optional redirects and webhook validation secret.

## Crypto Payments
Once the OxaPay API key is configured the bot can generate checkout links and sync payment status automatically.

1. Fill the OxaPay section in `.env` (at minimum `OXAPAY_API_KEY`) and restart the bot.
2. Open **Admin → Crypto payments** to toggle the feature, adjust invoice lifetime, select currencies, or provide webhook URLs. The page also fetches the account’s accepted coins for quick reference.
3. When a user confirms an order, they receive a “Pay with crypto” button linking to the OxaPay checkout. Admins get order notifications with track IDs and links.
4. Users can refresh order status from **My orders**; the bot calls OxaPay and updates the order to `Paid`, `Expired`, or `Cancelled` automatically.
5. (Optional) Configure `OXAPAY_CALLBACK_URL` and `OXAPAY_CALLBACK_SECRET` for future webhook processing.

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
- Wire webhook verification for OxaPay callbacks and reconcile partial/underpaid states.
- Build channel management, catalog CRUD, and support modules within the admin panel.
- Extend migrations and services as new features land.
