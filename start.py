import os
import subprocess
import sys
import platform
import time

def main():
    root_dir = os.path.dirname(os.path.abspath(__file__))
    backend_dir = os.path.join(root_dir, "backend")
    frontend_dir = os.path.join(root_dir, "frontend")
    
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
        
    # 3. Install backend requirements
    print("\nInstalling backend dependencies...")
    subprocess.run([venv_python, "-m", "pip", "install", "--upgrade", "pip"], check=True)
    subprocess.run([venv_pip, "install", "-r", os.path.join(backend_dir, "requirements.txt")], check=True)
    
    # 4. Build frontend
    print("\nBuilding frontend...")
    try:
        subprocess.run([npm_cmd, "install"], cwd=frontend_dir, check=True)
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
        
        # Start Frontend (using python's built-in http server)
        frontend_process = subprocess.Popen([venv_python, "-m", "http.server", "5173"], cwd=frontend_dir)
        processes.append(frontend_process)
        
        print("\n✅ All servers are running!")
        print("📡 Backend signaling: ws://127.0.0.1:8765")
        print("🖥️  Frontend:          http://127.0.0.1:5173/index.html")
        print("\n🛑 Press Ctrl+C to stop all servers gracefully.")
        
        # Keep the main thread alive while servers run
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n\nReceived Ctrl+C! Shutting down servers...")
    finally:
        # Gracefully terminate all child processes
        for p in processes:
            p.terminate()
            
        # Wait for them to actually close
        for p in processes:
            p.wait()
            
        print("✅ Servers stopped successfully.")

if __name__ == "__main__":
    main()
