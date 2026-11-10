"""Small terminal-safe progress display shared by CLI commands."""
from __future__ import annotations

import shutil
import sys
import unicodedata


def text_width(text: str) -> int:
    return sum(0 if unicodedata.combining(char) else
               2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1 for char in text)


def fit_text(text: str, columns: int) -> str:
    """Clip by terminal cells, including double-width Chinese characters."""
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    if text_width(text) <= columns:
        return text
    marker = '...' if columns >= 3 else '.' * max(0, columns)
    result, used = [], 0
    for char in text:
        width = text_width(char)
        if used + width > max(0, columns - len(marker)):
            break
        result.append(char)
        used += width
    return "".join(result) + marker


def clock_text(seconds: float) -> str:
    minutes, seconds = divmod(max(0, int(seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


def progress_text(prefix: str, done: int, total: int, columns: int, *, unit: str = "", elapsed: float = 0,
                  eta: float | None = None, detail: str = "") -> str:
    total = max(0, total)
    done = min(total, max(0, done))
    ratio = done / total if total else 1.0
    head = f"{prefix} {done}/{total}{unit}"
    tail = f" {ratio:4.0%}  已用 {clock_text(elapsed)}"
    if eta is not None and done > 0 and done < total:
        tail += f"  约余 {clock_text(eta)}"
    if detail:
        tail += f"  {detail}"
    bar_width = min(18, columns - text_width(head + tail) - 4)
    if bar_width >= 5:
        filled = round(ratio * bar_width)
        head += f" [{'#' * filled}{'-' * (bar_width - filled)}]"
    return fit_text(head + tail, columns)


def enable_vt(stream=None) -> bool:
    stream = stream if stream is not None else sys.stdout
    if not getattr(stream, "isatty", lambda: False)():
        return False
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        import msvcrt

        kernel32 = ctypes.windll.kernel32
        handle = msvcrt.get_osfhandle(stream.fileno())
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(ctypes.c_void_p(handle), ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(ctypes.c_void_p(handle), mode.value | 0x0004))
    except (AttributeError, OSError, ValueError):
        return False


class ProgressDisplay:
    def __init__(self, stream=None, *, ansi: bool | None = None, size=None):
        self.stream = stream if stream is not None else sys.stdout
        self.tty = bool(getattr(self.stream, "isatty", lambda: False)())
        self.ansi = self.tty and (enable_vt(self.stream) if ansi is None else ansi)
        self.size = size or (lambda: shutil.get_terminal_size((100, 24)))
        self.lines: list[str] = []
        self.rows = 0
        self.previous_width = 0
        self.previous_columns = 0

    @property
    def columns(self) -> int:
        return max(8, self.size().columns - 1)

    def _write(self, text: str) -> None:
        encoding = getattr(self.stream, "encoding", None)
        if encoding:
            text = text.encode(encoding, errors="replace").decode(encoding)
        self.stream.write(text)
        self.stream.flush()

    def _erase(self) -> None:
        if self.ansi and self.rows:
            self._write(f"\x1b[{self.rows}A\r\x1b[J")
        elif self.previous_width:
            self._write("\r" + " " * min(self.previous_width, self.columns) + "\r")
        self.rows = self.previous_width = 0

    def show(self, lines: list[str]) -> None:
        if not self.tty:
            for line in lines:
                self._write(line + "\n")
            return
        columns = self.columns
        maximum = max(1, min(6, self.size().lines - 4))
        if len(lines) > maximum:
            hidden = len(lines) - maximum + 1
            lines = lines[:maximum - 1] + [f"另有 {hidden} 项候选进度"]
        lines = [fit_text(line, columns) for line in lines]
        if lines == self.lines and columns == self.previous_columns:
            return
        if self.previous_columns and columns != self.previous_columns:
            # Resizing may have reflowed old rows. Start a fresh block instead
            # of moving the cursor into unrelated terminal history.
            self.finish()
        prefix = f"\x1b[{self.rows}A\r\x1b[J" if self.ansi and self.rows else ""
        if not self.ansi:
            self._erase()
        self.lines, self.previous_columns = lines, columns
        if self.ansi:
            self._write(prefix + "".join(line + "\x1b[K\n" for line in lines))
            self.rows = len(lines)
        elif lines:
            self._write("\r" + lines[-1])
            self.previous_width = text_width(lines[-1])

    def line(self, message: str) -> None:
        if self.tty:
            self._erase()
        self._write(message.rstrip("\r\n") + "\n")
        lines, self.lines = self.lines, []
        if self.tty and lines:
            self.show(lines)

    def finish(self) -> None:
        if self.previous_width:
            self._write("\n")
        self.lines = []
        self.rows = self.previous_width = self.previous_columns = 0
