import json
from pathlib import Path
import subprocess

from psychsandbox.workbench import stop


def test_stop_preserves_other_applications_and_other_projects(monkeypatch):
    project_python = str(Path(stop.__file__).resolve().parents[3] / ".venv/Scripts/python.exe")
    processes = [
        {"ProcessId": 101, "ExecutablePath": project_python,
         "CommandLine": f'"{project_python}" -m psychsandbox.workbench.server --port 8001'},
        {"ProcessId": 102, "ExecutablePath": project_python,
         "CommandLine": f'"{project_python}" -m psychsandbox.workbench.worker --lane long'},
        {"ProcessId": 103, "ExecutablePath": project_python,
         "CommandLine": f'"{project_python}" -m psychsandbox.cli --help'},
        {"ProcessId": 104, "ExecutablePath": r"D:\other\.venv\Scripts\python.exe",
         "CommandLine": r'"D:\other\.venv\Scripts\python.exe" -m psychsandbox.workbench.worker --lane short'},
        {"ProcessId": 7872, "ExecutablePath": r"C:\other\Manager.exe",
         "CommandLine": "Manager.exe"},
    ]
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(processes), stderr="")

    monkeypatch.setattr(stop.subprocess, "run", fake_run)
    monkeypatch.setattr(
        stop.subprocess, "check_output",
        lambda *args, **kwargs: "TCP    0.0.0.0:8000    0.0.0.0:0    LISTENING    7872\n",
    )

    stop.stop_all()

    assert not any("7872" in str(command) for command in calls)
    stopped = [command[command.index("/PID") + 1]
               for command in calls if isinstance(command, list) and command[0] == "taskkill"]
    assert set(stopped) == {"101", "102"}
    assert all("/T" in command for command in calls
               if isinstance(command, list) and command[0] == "taskkill")
