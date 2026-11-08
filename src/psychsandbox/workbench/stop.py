"""停止 PsychSandbox 工作台及其后台 Worker 进程"""
import json
from pathlib import Path
import re
import signal
import subprocess
import sys


def stop_all():
    print("[PsychSandbox] Stopping Workbench server and background workers...")
    stopped_count = 0

    project_python = Path(__file__).resolve().parents[3] / ".venv/Scripts/python.exe"
    ps_cmd = (
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); "
        "Get-CimInstance Win32_Process "
        "-Filter \"Name = 'python.exe' OR Name = 'pythonw.exe'\" | "
        "Select-Object ProcessId,ExecutablePath,CommandLine | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            check=True, capture_output=True, text=True, encoding="utf-8",
        )
        processes = json.loads(result.stdout) if result.stdout.strip() else []
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"[PsychSandbox] Could not inspect workbench processes: {exc}")
        return

    if isinstance(processes, dict):
        processes = [processes]
    for process in processes:
        if (process.get("ExecutablePath") or "").casefold() != str(project_python).casefold():
            continue
        if not re.search(
            r"(?:^|\s)-m\s+psychsandbox\.workbench\.(?:server|worker)(?:\s|$)",
            process.get("CommandLine") or "",
        ):
            continue
        pid = str(process["ProcessId"])
        result = subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True)
        if result.returncode == 0:
            print(f"  - Stopped workbench process tree (PID: {pid})")
            stopped_count += 1

    print(f"[PsychSandbox] Stopped {stopped_count} project workbench process trees.")


if __name__ == "__main__":
    stop_all()
