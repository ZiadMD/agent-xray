"""The ``xray`` command line.

xray tail [FILE_OR_DIR] [-f]   pretty-print a recording (default: latest in ./xray_runs)
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import TextIO

from .recorder import latest_recording
from .schema import Event, parse_event

# palette mirrors the viewer: cyan nodes, amber tokens, violet tools, green ok, red errors
_COLORS = {
    "dim": "\033[2m",
    "bold": "\033[1m",
    "cyan": "\033[38;2;92;225;230m",
    "amber": "\033[38;2;255;210;122m",
    "violet": "\033[38;2;167;139;250m",
    "green": "\033[38;2;124;255;178m",
    "red": "\033[38;2;255;77;109m",
    "text": "\033[38;2;201;209;224m",
    "reset": "\033[0m",
}


def _enable_windows_ansi() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        pass


class Printer:
    """Renders events as one line each; consecutive tokens of a message share one line."""

    def __init__(self, out: TextIO, color: bool) -> None:
        self.out = out
        self.color = color
        self._token_message: str | None = None

    def c(self, name: str, text: str) -> str:
        return f"{_COLORS[name]}{text}{_COLORS['reset']}" if self.color else text

    def ms(self, value: float) -> str:
        return self.c("dim", f"{value:.0f}ms")

    def _prefix(self, event: Event) -> str:
        return self.c("dim", f"{event.t / 1000:8.3f}s #{event.seq:<5}")

    def _line(self, event: Event, label: str, color: str, body: str) -> None:
        self.close_tokens()
        depth = "  " * len(event.ns)
        self.out.write(f"{self._prefix(event)} {depth}{self.c(color, f'{label:<10}')} {body}\n")

    def close_tokens(self) -> None:
        if self._token_message is not None:
            self.out.write(self.c("amber", "»") + "\n")
            self._token_message = None

    def print(self, event: Event) -> None:
        d = event.data
        match event.type:
            case "run_start":
                g = d.graph
                self._line(
                    event,
                    "run_start",
                    "bold",
                    f"{self.c('cyan', d.meta.graph_name)}  "
                    f"{len(g.nodes)} nodes, {len(g.edges)} edges  "
                    f"{self.c('dim', 'langgraph ' + d.meta.langgraph_version)}"
                    f"\n{' ' * 24}{self.c('dim', 'input ' + d.input_preview)}",
                )
            case "node_start":
                self._line(event, "▶ start", "cyan", self.c("bold", d.node))
            case "node_end":
                if d.error:
                    self._line(
                        event,
                        "✖ failed",
                        "red",
                        f"{d.node} {self.ms(d.duration_ms)}  {self.c('red', d.error)}",
                    )
                else:
                    out = f"  {self.c('dim', d.output_preview)}" if d.output_preview else ""
                    self._line(
                        event,
                        "■ end",
                        "cyan",
                        f"{d.node} {self.ms(d.duration_ms)}{out}",
                    )
            case "edge":
                self._line(event, "→ edge", "dim", f"{d.source} → {d.target}")
            case "token":
                if self._token_message != d.message_id:
                    self.close_tokens()
                    depth = "  " * len(event.ns)
                    label = self.c("amber", f"{'✦ tokens':<10}")
                    self.out.write(f"{self._prefix(event)} {depth}{label} {self.c('amber', '«')}")
                    self._token_message = d.message_id
                self.out.write(self.c("text", d.text.replace("\n", "⏎ ")))
            case "llm_end":
                self._line(
                    event,
                    "◆ llm",
                    "amber",
                    f"{d.node} {self.c('dim', d.model)}  "
                    f"in {d.input_tokens} / out {d.output_tokens} tok  {self.ms(d.latency_ms)}",
                )
            case "tool_start":
                self._line(
                    event,
                    "◐ tool",
                    "violet",
                    f"{d.tool} {self.c('dim', d.args_preview)}  {self.c('dim', 'in ' + d.node)}",
                )
            case "tool_end":
                mark = self.c("green", "ok") if d.ok else self.c("red", "failed")
                self._line(
                    event,
                    "◑ tool",
                    "violet",
                    f"{d.tool} {mark} {self.ms(d.duration_ms)}  {self.c('dim', d.result_preview)}",
                )
            case "custom":
                self._line(event, "✧ custom", "violet", f"{d.node or '?'}  {d.payload}")
            case "error":
                self._line(event, "✖ error", "red", f"{d.node or 'graph'}  {d.message}")
            case "run_end":
                t = d.totals
                color = "green" if d.status == "ok" else "red" if d.status == "error" else "amber"
                self._line(
                    event,
                    "run_end",
                    "bold",
                    f"{self.c(color, d.status)}  {t.duration_ms / 1000:.2f}s  "
                    f"tokens in {t.input_tokens} / out {t.output_tokens}  "
                    f"llm calls {t.llm_calls}  tool calls {t.tool_calls}",
                )
        self.out.flush()


def _follow_lines(path: Path, follow: bool) -> Iterator[bytes]:
    with path.open("rb") as fh:
        pending = b""
        while True:
            chunk = fh.readline()
            if chunk:
                pending += chunk
                if pending.endswith(b"\n"):
                    yield pending
                    pending = b""
                continue
            if not follow:
                if pending.strip():
                    yield pending
                return
            time.sleep(0.1)


def _resolve(target: str | None) -> Path:
    path = Path(target or "./xray_runs")
    if path.is_dir():
        latest = latest_recording(path)
        if latest is None:
            raise SystemExit(f"xray: no recordings (*.jsonl) in {path}")
        return latest
    if not path.exists():
        raise SystemExit(f"xray: {path} does not exist")
    return path


def cmd_tail(args: argparse.Namespace) -> int:
    path = _resolve(args.target)
    out = sys.stdout
    if hasattr(out, "reconfigure"):
        out.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    color = out.isatty() and not os.environ.get("NO_COLOR") and not args.no_color
    if color:
        _enable_windows_ansi()
    printer = Printer(out, color)
    out.write(printer.c("dim", f"── {path}") + "\n")
    try:
        for line in _follow_lines(path, args.follow):
            if not line.strip():
                continue
            try:
                event = parse_event(line)
            except ValueError as exc:
                printer.close_tokens()
                out.write(printer.c("red", f"invalid event: {exc}") + "\n")
                continue
            printer.print(event)
            if args.follow and event.type == "run_end":
                break
    except KeyboardInterrupt:
        pass
    printer.close_tokens()
    return 0


def _open_and_hold(url: str, open_browser: bool, what: str) -> None:
    import threading
    import webbrowser

    print(f"{what}: {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass


def start_viewer(directory: Path, port: int):  # type: ignore[no-untyped-def]
    """Serve the viewer over a directory of recordings (no live events)."""
    from .server import EventBus, ViewerServer, create_app

    server = ViewerServer(create_app(EventBus(), lambda: directory), port=port)
    server.start()
    return server


def cmd_serve(args: argparse.Namespace) -> int:
    directory = Path(args.dir)
    if not directory.is_dir():
        raise SystemExit(f"xray: {directory} is not a directory")
    server = start_viewer(directory, args.port)
    _open_and_hold(server.url, not args.no_browser, f"Agent X-Ray: browsing {directory}")
    server.stop()
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.is_file():
        raise SystemExit(f"xray: {path} does not exist")
    server = start_viewer(path.resolve().parent, args.port)
    url = f"{server.url}/?run={path.stem}"
    _open_and_hold(url, not args.no_browser, f"Agent X-Ray: replaying {path.name}")
    server.stop()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xray", description="Agent X-Ray command line.")
    sub = parser.add_subparsers(dest="command", required=True)

    tail = sub.add_parser("tail", help="pretty-print the events of a recording")
    tail.add_argument(
        "target",
        nargs="?",
        help="a .jsonl recording or a directory (default: ./xray_runs, latest file)",
    )
    tail.add_argument(
        "-f", "--follow", action="store_true", help="keep printing until the run ends"
    )
    tail.add_argument("--no-color", action="store_true", help="disable colors")
    tail.set_defaults(func=cmd_tail)

    serve = sub.add_parser("serve", help="serve the viewer to browse past recordings")
    serve.add_argument(
        "--dir", default="./xray_runs", help="recordings directory (default: ./xray_runs)"
    )
    serve.add_argument("--port", type=int, default=7777)
    serve.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    serve.set_defaults(func=cmd_serve)

    replay = sub.add_parser("replay", help="open the viewer in replay mode for a recording")
    replay.add_argument("file", help="a .jsonl recording")
    replay.add_argument("--port", type=int, default=7777)
    replay.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    replay.set_defaults(func=cmd_replay)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
