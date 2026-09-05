from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.settings import Settings
from app.db.backup import backup_database
from app.db.migrations import migrate_database, migration_status


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage the teradataevsui SQLite schema.")
    parser.add_argument("command", choices=("migrate", "status", "backup"), nargs="?", default="migrate")
    parser.add_argument("--output", type=Path, help="Backup destination; defaults below data/backups.")
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.command == "backup":
        destination = backup_database(settings.database_path, args.output)
        print(json.dumps({"database_path": str(settings.database_path), "backup_path": str(destination)}, indent=2))
    elif args.command == "migrate":
        applied = migrate_database(settings.database_path)
        print(json.dumps({"newly_applied_versions": applied, **migration_status(settings.database_path)}, indent=2))
    else:
        print(json.dumps(migration_status(settings.database_path), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
