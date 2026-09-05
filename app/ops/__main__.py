from __future__ import annotations

import argparse
import json

from app.core.settings import Settings
from app.db.migrations import migrate_database
from app.db.sqlite import SQLiteDatabase
from app.repositories import ArtifactRepository, JobRepository
from app.services.artifact_lifecycle import ArtifactLifecycle
from app.services.job_worker import PersistentJobWorker
from app.services.maintenance_jobs import ARTIFACT_CLEANUP_JOB, build_maintenance_job_handlers


def main() -> int:
    parser = argparse.ArgumentParser(description="teradataevsui operational maintenance.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("inventory")
    cleanup = subparsers.add_parser("cleanup-artifacts")
    cleanup.add_argument("--apply", action="store_true", help="Delete expired tracked files.")
    subparsers.add_parser("jobs")
    enqueue_cleanup = subparsers.add_parser("enqueue-artifact-cleanup")
    enqueue_cleanup.add_argument("--apply", action="store_true", help="Delete instead of previewing expired files.")
    run_jobs = subparsers.add_parser("run-jobs")
    run_jobs.add_argument("--max-jobs", type=int, default=100)
    args = parser.parse_args()

    settings = Settings.from_env()
    migrate_database(settings.database_path)
    database = SQLiteDatabase(settings.database_path)
    jobs = JobRepository(database)
    if args.command == "jobs":
        print(json.dumps(jobs.list_recent(), ensure_ascii=False, indent=2))
        return 0

    lifecycle = ArtifactLifecycle(
        ArtifactRepository(database),
        root=settings.project_dir / "uploads",
    )
    if args.command == "enqueue-artifact-cleanup":
        if args.apply and not settings.artifact_cleanup_enabled:
            parser.error("Set EVSUI_ARTIFACT_CLEANUP_ENABLED=true before using --apply.")
        queued = jobs.create(kind=ARTIFACT_CLEANUP_JOB, payload={"apply": bool(args.apply)})
        print(json.dumps(queued, ensure_ascii=False, indent=2))
        return 0
    if args.command == "run-jobs":
        worker = PersistentJobWorker(
            jobs,
            handlers=build_maintenance_job_handlers(
                lifecycle,
                cleanup_enabled=settings.artifact_cleanup_enabled,
            ),
        )
        recovered = worker.recover_interrupted(stale_seconds=settings.job_stale_seconds)
        completed = worker.run_until_empty(max_jobs=args.max_jobs)
        print(json.dumps({"recovered": recovered, "completed": completed}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "inventory":
        print(json.dumps(lifecycle.inventory(), indent=2))
        return 0
    if args.apply and not settings.artifact_cleanup_enabled:
        parser.error("Set EVSUI_ARTIFACT_CLEANUP_ENABLED=true before using --apply.")
    print(json.dumps(lifecycle.cleanup_expired(apply=args.apply), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
