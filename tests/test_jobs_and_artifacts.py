from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from app.db.migrations import migrate_database
from app.db.sqlite import SQLiteDatabase
from app.repositories import ArtifactRepository, JobRepository
from app.services.artifact_lifecycle import ArtifactLifecycle
from app.services.job_worker import PersistentJobWorker
from app.services.maintenance_jobs import ARTIFACT_CLEANUP_JOB, build_maintenance_job_handlers
from app.services.credential_vault import CredentialVault


class JobsAndArtifactsTests(unittest.TestCase):
    def _database(self, directory: str) -> SQLiteDatabase:
        path = Path(directory) / "evsui.db"
        migrate_database(path)
        return SQLiteDatabase(path)

    def test_persistent_worker_completes_a_queued_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            jobs = JobRepository(self._database(tmpdir))
            created = jobs.create(kind="add", payload={"left": 2, "right": 3})
            worker = PersistentJobWorker(
                jobs,
                handlers={
                    "add": lambda payload, heartbeat: (
                        heartbeat(50) or {"value": payload["left"] + payload["right"]}
                    )
                },
            )

            completed = worker.run_once()

            self.assertEqual(completed["id"], created["id"])
            self.assertEqual(completed["status"], "succeeded")
            self.assertEqual(completed["progress"], 100)
            self.assertEqual(completed["result"], {"value": 5})

    def test_failed_job_error_is_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            jobs = JobRepository(self._database(tmpdir))
            jobs.create(kind="fail")

            def fail(_payload, _heartbeat):
                raise RuntimeError("api_key=secret-value")

            completed = PersistentJobWorker(jobs, handlers={"fail": fail}).run_once()

            self.assertEqual(completed["status"], "failed")
            self.assertNotIn("secret-value", completed["error"])

    def test_sensitive_payload_is_encrypted_and_removed_after_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database = self._database(tmpdir)
            vault = CredentialVault(
                database_path=database.path,
                runtime_dir=Path(tmpdir) / "pem_runtime",
            )
            jobs = JobRepository(database, credential_vault=vault)
            created = jobs.create(
                kind="secret",
                payload={"name": "demo"},
                secret_payload={"provider_api_key": "never-plaintext"},
            )
            self.assertEqual(created["secret_payload"], {})
            with database.connect() as connection:
                stored = connection.execute(
                    "SELECT payload_json, secret_payload_ciphertext FROM jobs WHERE id=?",
                    (created["id"],),
                ).fetchone()
            self.assertNotIn("never-plaintext", stored["payload_json"])
            self.assertNotIn("never-plaintext", stored["secret_payload_ciphertext"])

            claimed = jobs.claim_next(kinds={"secret"})
            self.assertEqual(claimed["secret_payload"]["provider_api_key"], "never-plaintext")
            jobs.succeed(created["id"], {"ok": True})

            with database.connect() as connection:
                ciphertext = connection.execute(
                    "SELECT secret_payload_ciphertext FROM jobs WHERE id=?",
                    (created["id"],),
                ).fetchone()[0]
            self.assertEqual(ciphertext, "")

    def test_worker_does_not_persist_a_secret_echoed_by_a_handler(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database = self._database(tmpdir)
            vault = CredentialVault(
                database_path=database.path,
                runtime_dir=Path(tmpdir) / "pem_runtime",
            )
            jobs = JobRepository(database, credential_vault=vault)
            jobs.create(
                kind="echo",
                secret_payload={"provider_api_key": "runtime-only-secret"},
            )
            completed = PersistentJobWorker(
                jobs,
                handlers={"echo": lambda payload, _heartbeat: {"message": payload["provider_api_key"]}},
            ).run_once()

            self.assertNotIn("runtime-only-secret", str(completed["result"]))

    def test_maintenance_worker_runs_cleanup_as_a_persistent_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database = self._database(tmpdir)
            jobs = JobRepository(database)
            upload_root = Path(tmpdir) / "uploads"
            upload_root.mkdir()
            lifecycle = ArtifactLifecycle(ArtifactRepository(database), root=upload_root)
            jobs.create(kind=ARTIFACT_CLEANUP_JOB, payload={"apply": False})
            worker = PersistentJobWorker(
                jobs,
                handlers=build_maintenance_job_handlers(lifecycle, cleanup_enabled=False),
            )

            completed = worker.run_once()

            self.assertEqual(completed["status"], "succeeded")
            self.assertFalse(completed["result"]["apply"])
            self.assertEqual(completed["result"]["candidate_count"], 0)

    def test_artifact_cleanup_is_dry_run_by_default_and_root_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database = self._database(tmpdir)
            upload_root = Path(tmpdir) / "uploads"
            upload_root.mkdir()
            artifact_path = upload_root / "result.json"
            artifact_path.write_text("{}", encoding="utf-8")
            artifacts = ArtifactRepository(database)
            lifecycle = ArtifactLifecycle(artifacts, root=upload_root)
            registered = lifecycle.register_file(artifact_path, kind="result")
            with database.connect() as connection:
                connection.execute(
                    "UPDATE artifacts SET expires_at=? WHERE id=?",
                    (int(time.time()) - 1, registered["id"]),
                )

            preview = lifecycle.cleanup_expired()

            self.assertEqual(preview[0]["status"], "would-delete")
            self.assertTrue(artifact_path.exists())
            applied = lifecycle.cleanup_expired(apply=True)
            self.assertEqual(applied[0]["status"], "deleted")
            self.assertFalse(artifact_path.exists())
            with self.assertRaises(ValueError):
                lifecycle.register_file(Path(tmpdir) / "outside.txt", kind="unsafe")


if __name__ == "__main__":
    unittest.main()
