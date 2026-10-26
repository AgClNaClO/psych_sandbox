"""停止 PsychSandbox 工作台及其后台 Worker 进程"""
import os
import signal
import subprocess
import sys


def stop_all():
    print("[PsychSandbox] Stopping Workbench server and background workers...")
    stopped_count = 0

    # 1. 查找占用 8000 端口的进程
    try:
        out = subprocess.check_output("netstat -aon", shell=True, text=True, errors="ignore")
        for line in out.splitlines():
            if ":8000" in line and "LISTENING" in line:
                parts = line.strip().split()
                if len(parts) >= 5:
                    try:
                        pid = int(parts[-1])
                        if pid != os.getpid() and pid > 0:
                            subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)
                            print(f"  - Terminated server process on port 8000 (PID: {pid})")
                            stopped_count += 1
                    except Exception:
                        pass
    except Exception as e:
        print(f"  - Port 8000 check notice: {e}")

    # 2. 查找 Worker 进程
    try:
        ps_cmd = "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*psychsandbox.workbench.worker*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], check=False, capture_output=True)
        print("  - Cleaned up background worker processes")
    except Exception as e:
        print(f"  - Worker cleanup notice: {e}")

    print("[PsychSandbox] All workbench processes have been stopped.")


if __name__ == "__main__":
    stop_all()
