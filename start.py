import os
import subprocess
import sys
import platform
import time
import socket


def _read_env_file(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    if not os.path.exists(path):
        return values
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                values[key] = value
    return values


def _first_int(*values: str, default: int) -> int:
    for v in values:
        if v is None:
            continue
        try:
            return int(v)
        except (TypeError, ValueError):
            continue
    return default


def _is_port_free(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def _pick_free_port(preferred: int, host: str = "127.0.0.1", max_tries: int = 50) -> int:
    for port in range(preferred, preferred + max_tries):
        if _is_port_free(port, host):
            return port
    raise RuntimeError(f"Failed to find free port starting from {preferred}")

def main():
    skip_update = "--skip-update" in sys.argv[1:]
    root_dir = os.path.dirname(os.path.abspath(__file__))
    backend_dir = os.path.join(root_dir, "backend")
    frontend_dir = os.path.join(root_dir, "frontend")
    backend_env = _read_env_file(os.path.join(backend_dir, ".env"))
    frontend_env = _read_env_file(os.path.join(frontend_dir, ".env"))

    signaling_port = _first_int(
        os.environ.get("SIGNALING_PORT"),
        backend_env.get("SIGNALING_PORT"),
        default=8765,
    )
    frontend_port = _first_int(
        os.environ.get("FRONTEND_PORT"),
        frontend_env.get("FRONTEND_PORT"),
        default=5173,
    )
    ws_url = (
        os.environ.get("WS_URL")
        or frontend_env.get("WS_URL")
        or f"ws://127.0.0.1:{signaling_port}"
    )
    
    venv_dir = os.path.join(backend_dir, ".venv")
    
    print("=== WebRTC 4 Cams Setup ===")
    
    # 1. Create virtual environment if it doesn't exist
    if not os.path.exists(venv_dir):
        print("Creating Python virtual environment...")
        subprocess.run([sys.executable, "-m", "venv", venv_dir], check=True)
        
    # 2. Determine paths based on OS
    if platform.system() == "Windows":
        venv_python = os.path.join(venv_dir, "Scripts", "python.exe")
        venv_pip = os.path.join(venv_dir, "Scripts", "pip.exe")
        npm_cmd = "npm.cmd"
    else:
        venv_python = os.path.join(venv_dir, "bin", "python")
        venv_pip = os.path.join(venv_dir, "bin", "pip")
        npm_cmd = "npm"
        
    # 3. Install/update dependencies unless explicitly skipped
    if skip_update:
        print("\nSkipping dependency updates (--skip-update).")
    else:
        print("\nInstalling backend dependencies...")
        subprocess.run([venv_python, "-m", "pip", "install", "--upgrade", "pip"], check=True)
        subprocess.run([venv_pip, "install", "-r", os.path.join(backend_dir, "requirements.txt")], check=True)
        
        print("\nInstalling frontend dependencies...")
        try:
            subprocess.run([npm_cmd, "install"], cwd=frontend_dir, check=True)
        except FileNotFoundError:
            print("WARNING: npm not found. Skipping frontend dependency install. Make sure Node.js is installed.")
    
    # 4. Build frontend
    print("\nBuilding frontend...")
    try:
        subprocess.run([npm_cmd, "run", "build"], cwd=frontend_dir, check=True)
    except FileNotFoundError:
        print("WARNING: npm not found. Skipping frontend build. Make sure Node.js is installed.")
    
    # 5. Start servers
    print("\n=== Starting Servers ===")
    processes = []
    try:
        # Start Backend
        backend_process = subprocess.Popen([venv_python, "server.py"], cwd=backend_dir)
        processes.append(backend_process)

        # Wait briefly so bind errors are visible early.
        time.sleep(0.8)
        if backend_process.poll() is not None:
            raise RuntimeError(
                f"Backend failed to start (check port {signaling_port} and backend/.env)."
            )

        chosen_frontend_port = frontend_port
        if not _is_port_free(frontend_port):
            chosen_frontend_port = _pick_free_port(frontend_port + 1)
            print(
                f"WARNING: frontend port {frontend_port} is busy; "
                f"using {chosen_frontend_port} instead."
            )

        # Start Frontend (using python's built-in http server)
        frontend_process = subprocess.Popen(
            [venv_python, "-m", "http.server", str(chosen_frontend_port)],
            cwd=frontend_dir,
        )
        processes.append(frontend_process)

        time.sleep(0.6)
        if frontend_process.poll() is not None:
            raise RuntimeError(
                f"Frontend failed to start on port {chosen_frontend_port}."
            )

        print("\n✅ All servers are running!")
        print(f"📡 Backend signaling: ws://127.0.0.1:{signaling_port}")
        print(f"🔌 Frontend WS URL:    {ws_url}")
        print(f"🖥️  Frontend:          http://127.0.0.1:{chosen_frontend_port}/index.html")
        print("\n🛑 Press Ctrl+C to stop all servers gracefully.")

        # Keep the main thread alive while servers run
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n\nReceived Ctrl+C! Shutting down servers...")
    except Exception as e:
        print(f"\n❌ Startup failed: {e}")
    finally:
        # Gracefully terminate all child processes
        for p in processes:
            if p.poll() is None:
                p.terminate()

        # Wait for them to actually close
        for p in processes:
            try:
                p.wait(timeout=5)
            except Exception:
                pass

        print("✅ Servers stopped successfully.")

if __name__ == "__main__":
    main()
