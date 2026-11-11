"""检查或停止本项目的工作台进程。"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


def _workbench_pids() -> list[str]:

    project_python = Path(__file__).resolve().parents[3] / ".venv/Scripts/python.exe"
    ps_cmd = (
        "$ErrorActionPreference = 'Stop'; "
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); "
        "Get-CimInstance Win32_Process "
        "-Filter \"Name = 'python.exe' OR Name = 'pythonw.exe'\" | "
        "Select-Object ProcessId,ExecutablePath,CommandLine | ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    processes = json.loads(result.stdout) if result.stdout.strip() else []
    if isinstance(processes, dict):
        processes = [processes]
    pids = []
    for process in processes:
        if (process.get("ExecutablePath") or "").casefold() != str(project_python).casefold():
            continue
        if not re.search(
            r"(?:^|\s)-m\s+psychsandbox\.workbench\.(?:server|worker)(?:\s|$)",
            process.get("CommandLine") or "",
        ):
            continue
        pids.append(str(process["ProcessId"]))
    return pids


def stop_all() -> int:
    pids = _workbench_pids()
    print("[PsychSandbox] Stopping Workbench server and background workers...")
    stopped_count = 0
    for _ in range(2):
        if not pids:
            break
        for pid in pids:
            result = subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True)
            if result.returncode == 0:
                print(f"  - Stopped workbench process tree (PID: {pid})")
                stopped_count += 1
            else:
                print(f"  - Could not stop workbench process tree (PID: {pid})", file=sys.stderr)
        # A launcher can start another server while the previous one is stopping.
        pids = _workbench_pids()

    print(f"[PsychSandbox] Stopped {stopped_count} project workbench process trees.")
    if pids:
        print("[PsychSandbox] Workbench processes are still running.", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check or stop project Workbench processes")
    parser.add_argument("--check", action="store_true", help="Check that the Workbench is stopped")
    args = parser.parse_args(argv)
    try:
        if not args.check:
            return stop_all()
        pids = _workbench_pids()
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError):
        print("[PsychSandbox] Could not inspect or stop workbench processes.", file=sys.stderr)
        return 1

    if pids:
        print(
            "[PsychSandbox] Workbench processes are already running. "
            "Run stop_workbench.bat before relaunching to load code changes.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
