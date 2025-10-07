# Changelog

## [Unreleased]

### Added
- Core MariaDB-backed data layer with async SQLAlchemy session, product/order models, and Alembic migration pipeline.
- Structured configuration, structured logging, and async bot bootstrap with owner-only access middleware.
- Subscription enforcement middleware with inline join flow and admin toggle.
- OxaPay crypto checkout client/service with configurable currencies, lifetime, mixed payments, and automatic order status sync.
- Admin crypto payments console for toggling availability, updating invoice behaviour, and fetching accepted currencies.
- User order summaries now display OxaPay payment links, track IDs, and refresh buttons while awaiting payment.
- Admin product management module with:
  - Inline dashboard to list, view, activate/deactivate, edit, and delete products.
  - Full product creation wizard (name, pricing, inventory, ordering) with validation.
  - Purchase-form builder supporting dynamic question types, required flags, and option lists.
- Headless product/question repositories and service layer for slug generation and business rules.
- Docker/Docker Compose stack with automatic migrations and MariaDB health checks.
- CHANGELOG.md for release tracking.

### Fixed
- Logging serializer compatibility with aiogram/structlog stack (orjson default handling).

### Notes
- All admin flows remain owner-only; user-facing product browsing still uses previous placeholder responses.
