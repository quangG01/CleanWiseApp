# Monthly favorite workers

The dashboard at `/dashboard` now includes an independent month selector, three
monthly KPIs, a twelve-month chart for the selected year, comparison with the
previous month, and the top ten workers for the selected month. The report period
selector for revenue/orders does not change this independently selected month.

## Meaning

A count represents a distinct customer adding a worker to favorites during that
Vietnam calendar month (`Asia/Ho_Chi_Minh`, UTC+7). The same customer can favorite
several workers. Adding, removing and re-adding the same worker in one month
counts once. A later-month re-add counts in that month. Simply retaining an
existing favorite into a later month does not produce a new count. Removing a
favorite does not delete its historical monthly record. Workers who have since
become inactive stay in historical rankings with a status label. Ties use worker
ID for stable ordering. Empty months are returned with zero values.

This is separate from `favorite_count_current` in the existing worker report,
which remains the number of customers currently saving a worker.

## API

Admin only: `GET /api/admin/reports/favorite-workers/?year=2026&month=10&limit=10`.
Year range 2000–2100, month 1–12, limit 1–50; missing year/month use today's Vietnam
year/month. The standard envelope contains summary, timeline, top_workers, period,
timezone and basis. change_percent is null when the previous month has no entries.

## Storage and migration

worker.0009 creates WorkerFavoriteMonthlyEntry with a unique customer/worker/month
constraint and month/worker index. worker.0010 backfills retained favorite links
using their original created_at in Vietnam time, marked BACKFILL. Favorites
removed before this feature existed cannot be reconstructed. The UI identifies
selected-month data containing backfilled entries as potentially incomplete.

The customer add-favorite service records entries atomically with creating the
favorite link. Idempotent adds do not add an entry. New direct ORM/bulk inserts
must explicitly create the historical entry when intended; the dedicated seed
command does so. Delete-favorite behavior remains compatible with both apps.

## Demo data

```powershell
myenv\Scripts\python.exe manage.py migrate bookings --settings=core.settings.dev
myenv\Scripts\python.exe manage.py migrate worker --settings=core.settings.dev
myenv\Scripts\python.exe manage.py seed_monthly_favorites --date 2026-10-23 --months 12 --settings=core.settings.dev
```

The command requires DEBUG=True and a nonfuture anchor date. Default span is 12
months (up to 24). It creates eight named worker accounts, 32 customer accounts,
and distinct monthly favorites with varying leaders and counts. Current-month
favorites also appear in the customer favorites table. Demo accounts use the
`cw_fav_demo_` prefix and unusable passwords; existing account credentials and
records are not modified. Reruns do not duplicate rows.

Eligibility fixtures use `CW-FAV-DEMO-` booking codes and a dedicated
CW_FAVORITE_DEMO service. They are completed zero-value sessions with zero-value
earning rows, so they do contribute demo order/session counts but do not create
missing-earnings alerts, payment transactions, notifications or balance changes.
Bookings, assignments and historical entries are bulk inserted intentionally to
avoid real workflow signals and outbound notifications. The whole command runs
in one transaction and rolls back on failure. This is test data for development,
not production performance data.

## Validation

```powershell
myenv\Scripts\python.exe manage.py test apps.analytics apps.worker.tests.CustomerFavoriteWorkerAPITests --settings=core.settings.test --noinput
```

Tests cover permissions, input validation, UTC/Vietnam month boundaries, toggling,
historical preservation, January comparison, tie sorting, zero buckets, duplicate
constraints and seed idempotency with unchanged wallets and no notifications.
Run TypeScript, ESLint and the Next.js production build from CleanWiseDashboard.

## Development verification on 2026-10-23

Applied worker.0009/0010 and the existing additive bookings.0013 prerequisite.
Seeded 1,628 monthly entries from November 2025 through October 2026, 170 current
favorite links, eight demo workers, 32 demo customers and 254 zero-value eligibility
sessions. A second run created zero rows. The authenticated admin endpoint returned
HTTP 200; October 2026 has 180 entries including ten existing/backfilled entries,
with 36 distinct customers and 18 workers. The demo-only October count is 170.

Backend report/favorite tests passed (32 tests plus the added backfill test).
Dashboard TypeScript and targeted ESLint passed. `next build --webpack` completed
successfully. This machine's default Turbopack build fails while creating the
CSS processing child process, even outside the sandbox; no bundler configuration
was changed by this feature.
