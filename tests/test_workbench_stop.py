import json
from pathlib import Path
import subprocess

import pytest

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
        if command[0] == "taskkill":
            pid = command[command.index("/PID") + 1]
            processes[:] = [process for process in processes if str(process["ProcessId"]) != pid]
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(processes), stderr="")

    monkeypatch.setattr(stop.subprocess, "run", fake_run)
    monkeypatch.setattr(
        stop.subprocess, "check_output",
        lambda *args, **kwargs: "TCP    0.0.0.0:8000    0.0.0.0:0    LISTENING    7872\n",
    )

    assert stop.main(["--check"]) == 1
    assert [command[0] for command in calls] == ["powershell"]
    assert stop.main([]) == 0

    assert not any("7872" in str(command) for command in calls)
    stopped = [command[command.index("/PID") + 1]
               for command in calls if isinstance(command, list) and command[0] == "taskkill"]
    assert set(stopped) == {"101", "102"}
    assert all("/T" in command for command in calls
               if isinstance(command, list) and command[0] == "taskkill")


@pytest.mark.parametrize("exits_after_retry", [True, False])
def test_stop_rechecks_workbench_processes_after_killing(monkeypatch, exits_after_retry):
    remaining = iter([["101"], ["102"], [] if exits_after_retry else ["102"]])
    stopped = []

    def kill(command, **kwargs):
        assert command[0] == "taskkill"
        stopped.append(command[command.index("/PID") + 1])
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(stop, "_workbench_pids", lambda: next(remaining))
    monkeypatch.setattr(stop.subprocess, "run", kill)

    assert stop.main([]) == int(not exits_after_retry)
    assert stopped == ["101", "102"]


@pytest.mark.parametrize("inspection_fails", [False, True])
def test_launch_preflight_requires_successful_process_inspection(monkeypatch, inspection_fails):
    def inspect(command, **kwargs):
        assert command[0] == "powershell"
        if inspection_fails:
            raise subprocess.CalledProcessError(1, command)
        unrelated = {
            "ProcessId": 123, "ExecutablePath": r"D:\other\.venv\Scripts\python.exe",
            "CommandLine": r'"D:\other\.venv\Scripts\python.exe" -m psychsandbox.workbench.server',
        }
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(unrelated))

    monkeypatch.setattr(stop.subprocess, "run", inspect)
    assert stop.main(["--check"]) == int(inspection_fails)
