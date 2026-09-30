#!/bin/sh
set -e

echo "[entrypoint] SupportFlow AI Backend Container Starting..."

# Wait for PostgreSQL database to be reachable
echo "[entrypoint] Checking PostgreSQL database connectivity..."
python << 'EOF'
import os
import sys
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def wait_for_db():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("[entrypoint] WARNING: DATABASE_URL not set, skipping DB check.")
        return

    max_retries = 30
    for attempt in range(1, max_retries + 1):
        engine = None
        try:
            engine = create_async_engine(db_url)
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            print(f"[entrypoint] PostgreSQL is ready and reachable (attempt {attempt}).")
            return
        except Exception as exc:
            print(f"[entrypoint] DB not ready yet (attempt {attempt}/{max_retries}): {exc}")
            await asyncio.sleep(1)
        finally:
            if engine:
                await engine.dispose()

    print("[entrypoint] ERROR: Could not connect to PostgreSQL within timeout.")
    sys.exit(1)

asyncio.run(wait_for_db())
EOF

# Run Alembic migrations
echo "[entrypoint] Applying database migrations (alembic upgrade head)..."
alembic upgrade head
echo "[entrypoint] Migrations applied successfully."

# Hand over to application command
echo "[entrypoint] Executing CMD: $@"
exec "$@"
