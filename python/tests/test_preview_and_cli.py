from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from agent_xray import preview as pv
from agent_xray.cli import main as cli_main

import basic_fake
from conftest import XRay

FAKE_KEYS = [
    "sk-proj-abcdefghijklmnopqrstuvwxyz012345",
    "gsk_abcdefghijklmnopqrstuvwxyz0123456789",
    "AIzaSyA-abcdefghijklmnopqrstuvwxyz012345",
    "tvly-abcdefghijklmnopqrstuv",
    "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
]


@pytest.mark.parametrize("key", FAKE_KEYS)
def test_redacts_known_key_formats(key: str) -> None:
    out = pv.preview(f"calling with {key} now")
    assert key not in out
    assert pv.REDACTED in out


def test_redacts_key_value_pairs() -> None:
    out = pv.preview({"config": {"api_key": "supersecretvalue123", "model": "x"}})
    assert "supersecretvalue123" not in out
    assert '"model":"x"' in out


def test_preview_is_truncated() -> None:
    out = pv.preview("word " * 500)
    assert len(out) == pv.PREVIEW_CHARS
    assert out.endswith("…")


def test_preview_of_messages_keeps_the_tail() -> None:
    msgs = [HumanMessage(content=f"m{i}") for i in range(20)] + [
        AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "1"}])
    ]
    out = pv.preview({"messages": msgs})
    assert "earlier" in out and '"tool_calls":["t"]' in out
    assert "m19" in out and 'm0"' not in out


def test_payload_is_json_safe() -> None:
    class Thing:
        def __repr__(self) -> str:
            return "Thing()"

    data: Any = pv.payload({"thing": Thing(), "nums": (1, 2), "key": FAKE_KEYS[0]})
    assert data == {"thing": "Thing()", "nums": [1, 2], "key": f"{pv.REDACTED}"}


def test_secrets_never_reach_the_recording(xray: XRay) -> None:
    secret = FAKE_KEYS[1]
    inp = {**basic_fake.INPUT, "topic": f"agents (token {secret})"}
    xray.wrap(basic_fake.build_graph()).invoke(inp)
    text = next(xray.record_dir.glob("*.jsonl")).read_text(encoding="utf-8")
    assert secret not in text
    assert pv.REDACTED in text


def test_tail_prints_a_recording(xray: XRay, capsys: pytest.CaptureFixture[str]) -> None:
    xray.wrap(basic_fake.build_graph()).invoke(basic_fake.INPUT)
    path = next(xray.record_dir.glob("*.jsonl"))
    assert cli_main(["tail", str(path), "--no-color"]) == 0
    out = capsys.readouterr().out
    assert "run_start" in out and "basic_fake" in out
    assert "«Draft one: agents are cool and you should use them.»" in out
    assert "get_stats ok" in out
    assert "FlakyError" in out
    assert "run_end    ok" in out
    # a directory resolves to its latest recording
    assert cli_main(["tail", str(xray.record_dir), "--no-color"]) == 0


def test_tail_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        cli_main(["tail", str(tmp_path / "nope.jsonl")])
