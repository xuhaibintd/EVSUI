from __future__ import annotations

import asyncio
import unittest

from app.core.runtime_manager import TeradataRuntimeManager


class TeradataRuntimeManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_operations_are_serialized(self) -> None:
        manager = TeradataRuntimeManager()
        active = 0
        peak = 0

        async def work() -> None:
            nonlocal active, peak
            async with manager.operation():
                active += 1
                peak = max(peak, active)
                await asyncio.sleep(0.01)
                active -= 1

        await asyncio.gather(*(work() for _ in range(5)))

        self.assertEqual(peak, 1)

    async def test_reactivate_cleans_before_connecting_and_tracks_owner(self) -> None:
        manager = TeradataRuntimeManager()
        calls: list[str] = []

        manager.reactivate(
            identity="session:one:connection:7",
            cleanup=lambda: calls.append("cleanup"),
            connect=lambda: calls.append("connect"),
            authenticate=lambda: calls.append("authenticate"),
        )

        self.assertEqual(calls, ["cleanup", "connect", "authenticate"])
        self.assertEqual(manager.active_identity, "session:one:connection:7")
        self.assertEqual(manager.generation, 1)

    async def test_failed_reactivation_cleans_partial_context(self) -> None:
        manager = TeradataRuntimeManager()
        calls: list[str] = []

        def fail_authentication() -> None:
            raise RuntimeError("bad token")

        with self.assertRaisesRegex(RuntimeError, "bad token"):
            manager.reactivate(
                identity="session:one",
                cleanup=lambda: calls.append("cleanup"),
                connect=lambda: calls.append("connect"),
                authenticate=fail_authentication,
            )

        self.assertEqual(calls, ["cleanup", "connect", "cleanup"])
        self.assertEqual(manager.active_identity, "")


if __name__ == "__main__":
    unittest.main()
