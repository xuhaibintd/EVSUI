"""Local teradataevsui lifecycle controller. No PID-based kill or automatic queue deletion."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.process_lock import ProcessLock, lock_is_held


def read_record(directory: Path, component: str, suffix: str = "json") -> dict:
    try:
        record = json.loads((directory / f"{component}.{suffix}").read_text(encoding="utf-8"))
        if record.get("root") == str(ROOT) and record.get("component") == component:
            return record
    except (OSError, ValueError, AttributeError):
        pass
    return {}


def write_record(path: Path, record: dict) -> None:
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(record, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def process_identity(pid: int) -> str | None:
    """Read creation identity for exit waiting only; never signal a PID."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        api.OpenProcess.restype = wintypes.HANDLE
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        api.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        api.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        handle = api.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        try:
            code = wintypes.DWORD()
            if not api.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:
                return None
            times = [wintypes.FILETIME() for _ in range(4)]
            if not api.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)):
                return None
            return str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
        finally:
            api.CloseHandle(handle)
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return None if fields[0] == "Z" else fields[19]
    except (OSError, IndexError):
        return None


def running(directory: Path, component: str) -> bool:
    if lock_is_held(directory / f"{component}.lock"):
        return True
    # Wait for interpreter shutdown and the Windows virtualenv launcher as well.
    for suffix in ("json", "launch.json"):
        record = read_record(directory, component, suffix)
        identity = record.get("process_identity")
        if identity and process_identity(int(record["pid"])) == identity:
            return True
    return False


def request_stop(directory: Path, component: str) -> None:
    if not running(directory, component):
        return
    record = read_record(directory, component, "launch.json") or read_record(directory, component)
    if not record.get("token"):
        raise RuntimeError(f"Cannot verify {component} ownership; left it unchanged.")
    write_record(directory / f"{component}.stop", {"token": record["token"]})


def serve(args) -> int:
    directory = args.state_dir
    component = args.component
    stop = threading.Event()
    with ProcessLock(directory / f"{component}.lock"):
        record = {"root": str(ROOT), "component": component, "token": args.token,
                  "pid": os.getpid(), "process_identity": process_identity(os.getpid()),
                  "status": "starting", "port": args.port,
                  "bind_address": args.bind_address, "configuration": args.configuration,
                  "started_at": time.strftime("%Y-%m-%d %H:%M:%S"), "log": args.log}
        record_lock = threading.Lock()

        def mark(status):
            with record_lock:
                record["status"] = status
                write_record(directory / f"{component}.json", record)

        mark("starting")

        def watch_stop():
            while not stop.wait(0.2):
                try:
                    command = json.loads((directory / f"{component}.stop").read_text(encoding="utf-8"))
                    if command.get("token") == args.token:
                        mark("stopping")
                        stop.set()
                except (OSError, ValueError, AttributeError):
                    pass

        watcher = threading.Thread(target=watch_stop, daemon=True)
        watcher.start()
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, lambda *_: stop.set())
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
        try:
            if component == "web":
                import uvicorn
                server = uvicorn.Server(uvicorn.Config("app.main:app", host=args.bind_address,
                                                       port=args.port, workers=1, log_level="info"))

                def watch_web():
                    while not server.started and not stop.wait(0.1):
                        pass
                    if server.started and not stop.is_set():
                        mark("running")
                    stop.wait()
                    server.should_exit = True

                threading.Thread(target=watch_web, daemon=True).start()
                server.run()
            else:
                from app.core.settings import Settings
                from app.worker import run_worker
                run_worker(Settings.from_env(), stop, on_ready=lambda: mark("stopping" if stop.is_set() else "running"))
        except BaseException as error:
            # Do not copy raw settings/credentials or third-party exception text into status.
            record["error_type"] = type(error).__name__
            mark("failed")
            logging.error("%s failed (%s). Review configuration/dependencies and service logs.", component, type(error).__name__)
            return 1
        finally:
            stop.set()
            watcher.join(timeout=1)
            if record["status"] != "failed":
                mark("stopped")
    return 0


def web_healthy(record: dict) -> bool:
    address = record["bind_address"]
    if address == "0.0.0.0":
        address = "127.0.0.1"
    try:
        with build_opener(ProxyHandler({})).open(f"http://{address}:{record['port']}/healthz", timeout=1) as response:
            return response.status == 200 and json.loads(response.read()).get("status") == "ok"
    except Exception:
        return False


def start(args, components: list[str]) -> None:
    from app.core.settings import Settings
    settings = Settings.from_env()
    settings.validate_runtime()
    configuration = hashlib.sha256(json.dumps(asdict(settings), sort_keys=True, default=str).encode()).hexdigest()
    for component in ("web", "worker"):
        if running(args.state_dir, component):
            record = read_record(args.state_dir, component)
            if record.get("configuration") != configuration:
                raise RuntimeError("Running services use different settings. Stop all before changing environment settings.")
            if record.get("status") != "running":
                raise RuntimeError(f"{component} is {record.get('status', 'unknown')}; wait for stop/start to finish.")
            if component == "web" and (record.get("port") != args.port or record.get("bind_address") != args.bind_address):
                raise RuntimeError("Web address differs. Stop web before changing its address/port.")
    if "web" in components and not running(args.state_dir, "web"):
        with socket.socket() as probe:
            if os.name == "nt":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                probe.bind((args.bind_address, args.port))
            except OSError as error:
                raise RuntimeError(f"Port {args.port} is occupied/unavailable. No existing process was stopped.") from error
    if "worker" in components and not running(args.state_dir, "worker"):
        if lock_is_held(settings.database_path.with_suffix(".worker.lock")):
            raise RuntimeError("Another worker already uses this database; it was left unchanged.")
    started = []
    try:
        for component in components:
            if running(args.state_dir, component):
                print(f"{component}: already running")
                continue
            token = uuid.uuid4().hex
            print(f"{component}: starting...", flush=True)
            if component == "worker":
                print("Worker will execute queued jobs, including jobs already in the database.", flush=True)
            log = args.state_dir / "logs" / f"{component}-{time.strftime('%Y%m%d-%H%M%S')}-{token[:8]}.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            command = [sys.executable, str(Path(__file__).resolve()), "_serve", "--component", component,
                       "--state-dir", str(args.state_dir), "--token", token, "--configuration", configuration,
                       "--port", str(args.port), "--bind-address", args.bind_address, "--log", str(log)]
            with log.open("ab") as output:
                process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                                           start_new_session=os.name != "nt")
            write_record(args.state_dir / f"{component}.launch.json", {
                "root": str(ROOT), "component": component, "token": token,
                "pid": process.pid, "process_identity": process_identity(process.pid),
            })
            started.append((component, token))
            deadline = time.monotonic() + args.timeout
            while time.monotonic() < deadline:
                record = read_record(args.state_dir, component)
                if (record.get("token") == token and record.get("status") == "running"
                        and lock_is_held(args.state_dir / f"{component}.lock")):
                    if component != "web" or web_healthy(record):
                        print(f"{component}: running (PID {record['pid']}); log: {log}")
                        break
                if process.poll() is not None or (record.get("token") == token and record.get("status") == "failed"):
                    raise RuntimeError(f"{component} startup failed. Log: {log}")
                time.sleep(0.1)
            else:
                raise RuntimeError(f"{component} startup timed out. Log: {log}")
    except BaseException:
        # Token-specific requests even if the child has not yet written its state.
        for component, token in reversed(started):
            write_record(args.state_dir / f"{component}.stop", {"token": token})
        raise


def stop_services(args, components: list[str]) -> bool:
    for component in components:  # web first: stop accepting new work
        if running(args.state_dir, component):
            print(f"{component}: requesting graceful stop; waiting for active work to finish...", flush=True)
        request_stop(args.state_dir, component)
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        if not any(running(args.state_dir, component) for component in components):
            return True
        time.sleep(0.2)
    return not any(running(args.state_dir, component) for component in components)


def show_status(directory: Path, port: int = 8010, bind_address: str = "127.0.0.1") -> bool:
    active = False
    for component in ("web", "worker"):
        held = running(directory, component)
        record = read_record(directory, component)
        state = record.get("status", "starting") if held else ("failed" if record.get("status") == "failed" else "stopped")
        if held and state in {"stopped", "failed"}:
            state += " (process exiting)"
        if component == "web" and not held:
            address = record.get("bind_address", bind_address)
            address = "127.0.0.1" if address == "0.0.0.0" else address
            checked_port = record.get("port", port)
            try:
                with socket.create_connection((address, checked_port), timeout=0.25):
                    state = f"unmanaged listener on port {checked_port} (will not be stopped by these scripts)"
            except OSError:
                pass
        if held and component == "web" and state == "running" and not web_healthy(record):
            state = "unhealthy"
        print(f"{component}: {state}" + (f" (PID {record.get('pid', '?')})" if held else ""))
        if record.get("log"):
            print(f"  log: {record['log']}")
        active = active or held
    return active


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "restart", "status", "_serve"))
    parser.add_argument("--component", choices=("all", "web", "worker"), default="all")
    parser.add_argument("--port", type=int)
    parser.add_argument("--bind-address", choices=("127.0.0.1", "0.0.0.0"))
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--state-dir", type=Path, default=ROOT / ".run")
    for option in ("token", "configuration", "log"):
        parser.add_argument("--" + option, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    args.state_dir = args.state_dir.expanduser().resolve()
    os.chdir(ROOT)  # Relative settings resolve identically in controller and children.
    if args.timeout <= 0 or (args.port is not None and not 1 <= args.port <= 65535):
        parser.error("Timeout must be positive and port must be 1..65535.")
    args.state_dir.mkdir(parents=True, exist_ok=True)
    if args.action == "_serve":
        if args.component == "all" or not all((args.token, args.configuration, args.log, args.port, args.bind_address)):
            parser.error("Incomplete internal service arguments")
        return serve(args)
    try:
        with ProcessLock(args.state_dir / "controller.lock"):
            if args.action == "status":
                show_status(args.state_dir, args.port or 8010, args.bind_address or "127.0.0.1")
                return 0
            previous = read_record(args.state_dir, "web")
            args.port = args.port or previous.get("port", 8010)
            args.bind_address = args.bind_address or previous.get("bind_address", "127.0.0.1")
            components = ["web", "worker"] if args.component == "all" else [args.component]
            if args.action in {"stop", "restart"}:
                if not stop_services(args, components):
                    show_status(args.state_dir, args.port, args.bind_address)
                    print("Stop requested; current work is still draining. Nothing was force-killed. Retry status/stop later.")
                    return 2
            if args.action in {"start", "restart"}:
                start(args, components)
            show_status(args.state_dir, args.port, args.bind_address)
            return 0
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
