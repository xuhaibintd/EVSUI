from __future__ import annotations

import argparse
import json

from app.core.settings import Settings
from app.db.migrations import migrate_database, migration_status


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage the EVSUI SQLite schema.")
    parser.add_argument("command", choices=("migrate", "status"), nargs="?", default="migrate")
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.command == "migrate":
        applied = migrate_database(settings.database_path)
        print(json.dumps({"applied_versions": applied, **migration_status(settings.database_path)}, indent=2))
    else:
        print(json.dumps(migration_status(settings.database_path), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
