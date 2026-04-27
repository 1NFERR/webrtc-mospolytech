#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def is_port_free(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def pick_free_port(preferred: int, host: str = "127.0.0.1", max_tries: int = 50) -> int:
    for port in range(preferred, preferred + max_tries):
        if is_port_free(port, host):
            return port
    raise RuntimeError(f"Could not find free port in range {preferred}-{preferred + max_tries - 1}")


def ensure_env_file(service_dir: Path) -> None:
    env_path = service_dir / ".env"
    env_example = service_dir / ".env.example"
    if env_path.exists():
        return
    if env_example.exists():
        env_path.write_text(env_example.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"[env] Created {env_path}")


def run_checked(command: list[str], cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def require_binary(binary: str) -> None:
    if shutil.which(binary) is None:
        raise RuntimeError(f"Required command not found: {binary}")


def build_venv_paths(venv_dir: Path) -> tuple[Path, Path]:
    if platform.system() == "Windows":
        return venv_dir / "Scripts" / "python.exe", venv_dir / "Scripts" / "pip.exe"
    return venv_dir / "bin" / "python", venv_dir / "bin" / "pip"


def parse_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def build_frontend_command(frontend_dir: Path, npm_cmd: str, frontend_port: int) -> list[str]:
    vite_entry = frontend_dir / "node_modules" / "vite" / "bin" / "vite.js"
    if vite_entry.exists():
        return [
            "node",
            str(vite_entry),
            "--host",
            "0.0.0.0",
            "--port",
            str(frontend_port),
        ]
    return [npm_cmd, "run", "dev", "--", "--host", "0.0.0.0", "--port", str(frontend_port)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-update", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    signaling_dir = root / "signaling-server"
    frontend_dir = root / "frontend"
    car_dir = root / "car-video-client"

    for service_dir in (signaling_dir, frontend_dir, car_dir):
        ensure_env_file(service_dir)

    require_binary("node")
    npm_cmd = "npm.cmd" if platform.system() == "Windows" else "npm"
    require_binary(npm_cmd)

    venv_dir = car_dir / ".venv"
    if not venv_dir.exists():
        print("[car] Creating virtual environment")
        run_checked([sys.executable, "-m", "venv", str(venv_dir)], cwd=car_dir)

    venv_python, venv_pip = build_venv_paths(venv_dir)

    if not args.skip_update:
        print("[deps] Installing signaling-server dependencies")
        run_checked([npm_cmd, "install"], cwd=signaling_dir)

        print("[deps] Installing frontend dependencies")
        run_checked([npm_cmd, "install"], cwd=frontend_dir)

        print("[deps] Installing car-video-client dependencies")
        run_checked([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"], cwd=car_dir)
        run_checked([str(venv_pip), "install", "-r", "requirements.txt"], cwd=car_dir)
    else:
        print("[deps] Skipping dependency updates (--skip-update)")

    signaling_env_file = read_env_file(signaling_dir / ".env")
    frontend_env_file = read_env_file(frontend_dir / ".env")

    preferred_signaling = parse_int(
        os.environ.get("PORT") or signaling_env_file.get("PORT"),
        4000,
    )
    preferred_frontend = parse_int(
        os.environ.get("FRONTEND_PORT") or frontend_env_file.get("FRONTEND_PORT"),
        5173,
    )

    signaling_port = preferred_signaling if is_port_free(preferred_signaling) else pick_free_port(preferred_signaling + 1)
    frontend_port = preferred_frontend if is_port_free(preferred_frontend) else pick_free_port(preferred_frontend + 1)

    if signaling_port != preferred_signaling:
        print(f"[port] Signaling port {preferred_signaling} is busy, using {signaling_port}")
    if frontend_port != preferred_frontend:
        print(f"[port] Frontend port {preferred_frontend} is busy, using {frontend_port}")

    signaling_env = os.environ.copy()
    signaling_env["PORT"] = str(signaling_port)

    frontend_env = os.environ.copy()
    frontend_env["VITE_SIGNALING_WS_URL"] = f"ws://127.0.0.1:{signaling_port}/ws"
    frontend_env["VITE_SIGNALING_HTTP_URL"] = f"http://127.0.0.1:{signaling_port}"

    car_env = os.environ.copy()
    car_env["SIGNALING_WS_URL"] = f"ws://127.0.0.1:{signaling_port}/ws"

    processes: list[subprocess.Popen] = []

    try:
        print("[run] Starting signaling-server")
        processes.append(
            subprocess.Popen([npm_cmd, "run", "dev"], cwd=signaling_dir, env=signaling_env)
        )

        print("[run] Starting frontend")
        frontend_cmd = build_frontend_command(frontend_dir, npm_cmd, frontend_port)
        processes.append(
            subprocess.Popen(
                frontend_cmd,
                cwd=frontend_dir,
                env=frontend_env,
            )
        )

        print("[run] Starting car-video-client")
        processes.append(subprocess.Popen([str(venv_python), "main.py"], cwd=car_dir, env=car_env))

        print("")
        print(f"Signaling: ws://127.0.0.1:{signaling_port}/ws")
        print(f"Frontend:  http://127.0.0.1:{frontend_port}")
        print("Press Ctrl+C to stop all services")

        while True:
            for proc in processes:
                if proc.poll() is not None:
                    raise RuntimeError("One of the services exited unexpectedly")
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping services...")
    finally:
        for proc in processes:
            if proc.poll() is None:
                proc.terminate()
        for proc in processes:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        print("All services stopped")
    return 0


if __name__ == "__main__":
    if platform.system() == "Windows":
        signal.signal(signal.SIGINT, signal.default_int_handler)
    raise SystemExit(main())
