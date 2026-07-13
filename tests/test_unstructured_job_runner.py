from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.services.unstructured_job_runner import create_unstructured_on_demand_job


class _Response:
    def __init__(self, status_code: int, payload: dict, *, headers: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = str(payload)

    def json(self):
        return self._payload


class UnstructuredJobSubmissionTests(unittest.TestCase):
    def test_rate_limit_response_retries_using_server_delay(self) -> None:
        responses = [
            _Response(
                429,
                {
                    "code": "rate_limit_exceeded",
                    "message": "Job submission rate limit exceeded.",
                    "retry_after": 1,
                },
            ),
            _Response(200, {"id": "job-123"}),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "sample.pdf"
            source.write_bytes(b"pdf")
            with mock.patch(
                "app.services.unstructured_job_runner.httpx.post",
                side_effect=responses,
            ) as post_mock, mock.patch(
                "app.services.unstructured_job_runner.time.sleep"
            ) as sleep_mock:
                job_id, payload = create_unstructured_on_demand_job(
                    request_parameters={"workflow_nodes": []},
                    src=source,
                    api_key="secret",
                    api_url="https://example.invalid/api/v1",
                )

        self.assertEqual(job_id, "job-123")
        self.assertEqual(payload, {"id": "job-123"})
        self.assertEqual(post_mock.call_count, 2)
        sleep_mock.assert_called_once_with(1.35)

    def test_non_rate_limit_error_is_not_retried(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "sample.pdf"
            source.write_bytes(b"pdf")
            with mock.patch(
                "app.services.unstructured_job_runner.httpx.post",
                return_value=_Response(400, {"message": "bad request"}),
            ) as post_mock, self.assertRaisesRegex(RuntimeError, "status=400"):
                create_unstructured_on_demand_job(
                    request_parameters={"workflow_nodes": []},
                    src=source,
                    api_key="secret",
                    api_url="https://example.invalid/api/v1",
                )

        self.assertEqual(post_mock.call_count, 1)


if __name__ == "__main__":
    unittest.main()
