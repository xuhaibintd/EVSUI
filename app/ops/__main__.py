from __future__ import annotations

import argparse
import json

from app.core.settings import Settings
from app.db.migrations import migrate_database
from app.db.sqlite import SQLiteDatabase
from app.repositories import ArtifactRepository, JobRepository
from app.services.artifact_lifecycle import ArtifactLifecycle


def main() -> int:
    parser = argparse.ArgumentParser(description="EVSUI operational maintenance.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("inventory")
    cleanup = subparsers.add_parser("cleanup-artifacts")
    cleanup.add_argument("--apply", action="store_true", help="Delete expired tracked files.")
    subparsers.add_parser("jobs")
    args = parser.parse_args()

    settings = Settings.from_env()
    migrate_database(settings.database_path)
    database = SQLiteDatabase(settings.database_path)
    if args.command == "jobs":
        print(json.dumps(JobRepository(database).list_recent(), ensure_ascii=False, indent=2))
        return 0

    lifecycle = ArtifactLifecycle(
        ArtifactRepository(database),
        root=settings.project_dir / "uploads",
    )
    if args.command == "inventory":
        print(json.dumps(lifecycle.inventory(), indent=2))
        return 0
    if args.apply and not settings.artifact_cleanup_enabled:
        parser.error("Set EVSUI_ARTIFACT_CLEANUP_ENABLED=true before using --apply.")
    print(json.dumps(lifecycle.cleanup_expired(apply=args.apply), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
