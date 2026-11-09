"""Regression coverage for temporary directories under restricted Windows tokens."""
from pathlib import Path
import tempfile


def test_pytest_temporary_directories_remain_writable(tmp_path, tmp_path_factory):
    for directory in (tmp_path, tmp_path_factory.mktemp("permissions")):
        child = directory / "owner-only"
        child.mkdir(mode=0o700)
        output = child / "probe.txt"
        output.write_text("writable", encoding="utf-8")
        assert output.read_text(encoding="utf-8") == "writable"


def test_standard_library_temporary_directory_remains_writable(tmp_path):
    with tempfile.TemporaryDirectory(dir=tmp_path) as directory:
        output = Path(directory) / "probe.txt"
        output.write_text("writable", encoding="utf-8")
        assert output.read_text(encoding="utf-8") == "writable"
    assert not Path(directory).exists()
