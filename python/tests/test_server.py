"""Server: event bus, WebSocket, recordings API and the background uvicorn thread."""

from __future__ import annotations

import importlib
import json
import threading
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from websockets.sync.client import connect

from agent_xray.server import EventBus, ViewerServer, create_app, list_runs
from agent_xray.watch import Session, WatchedGraph

import basic_fake
from conftest import XRay

# the test client always sends "Host: testserver" on WebSocket handshakes
LOCAL = {"host": "localhost"}


def _events(raw: str) -> list[dict]:
    """Events in one WebSocket message ({"sync": true} markers carry none)."""
    data = json.loads(raw)
    return data if isinstance(data, list) else []


def _run_into(session: Session) -> None:
    WatchedGraph(basic_fake.build_graph(), session).invoke(basic_fake.INPUT)


def test_bus_keeps_running_and_latest_finished_runs() -> None:
    session = Session()
    _run_into(session)
    first = session.bus.backlog()
    assert json.loads(first[0])["type"] == "run_start"
    assert json.loads(first[-1])["type"] == "run_end"
    _run_into(session)
    second = session.bus.backlog()
    run_ids = {json.loads(m)["run_id"] for m in second}
    assert len(run_ids) == 1 and json.loads(first[0])["run_id"] not in run_ids


def test_runs_api(xray: XRay) -> None:
    xray.wrap(basic_fake.build_graph()).invoke(basic_fake.INPUT)
    client = TestClient(
        create_app(EventBus(), lambda: xray.record_dir), base_url="http://localhost"
    )
    runs = client.get("/api/runs").json()
    assert len(runs) == 1
    run = runs[0]
    assert run["name"] == "basic_fake"
    assert run["status"] == "ok"
    assert run["duration_ms"] > 0
    assert run["id"] == next(xray.record_dir.glob("*.jsonl")).stem
    body = client.get(f"/api/runs/{run['id']}")
    assert body.status_code == 200
    lines = body.text.strip().splitlines()
    assert json.loads(lines[0])["type"] == "run_start"
    assert json.loads(lines[-1])["type"] == "run_end"
    assert client.get("/api/runs/nope").status_code == 404
    assert client.get("/api/runs/..%2F..%2Fpyproject").status_code == 404


def test_runs_api_lists_running_and_skips_garbage(tmp_path: Path) -> None:
    session = Session()
    session.configure(record_dir=tmp_path)
    _run_into(session)
    path = next(tmp_path.glob("*.jsonl"))
    lines = path.read_bytes().splitlines()
    (tmp_path / "20990101-000000_partial_abcd1234.jsonl").write_bytes(b"\n".join(lines[:5]) + b"\n")
    (tmp_path / "junk.jsonl").write_bytes(b"not json\n")
    statuses = {r.id: r.status for r in list_runs(tmp_path)}
    assert statuses == {path.stem: "ok", "20990101-000000_partial_abcd1234": "running"}
    assert list_runs(None) == [] and list_runs(tmp_path / "missing") == []


def test_websocket_backlog_then_live() -> None:
    session = Session()
    _run_into(session)  # finished before the tab connects
    client = TestClient(create_app(session.bus, lambda: None), base_url="http://localhost")
    with client.websocket_connect("/ws", headers=LOCAL) as ws:
        backlog = json.loads(ws.receive_text())
        assert isinstance(backlog, list)
        assert json.loads(ws.receive_text()) == {"sync": True}  # end of history
        assert backlog[0]["type"] == "run_start" and backlog[-1]["type"] == "run_end"
        assert [e["seq"] for e in backlog] == list(range(len(backlog)))

        worker = threading.Thread(target=_run_into, args=(session,))
        worker.start()
        live: list[dict] = []
        while not live or live[-1]["type"] != "run_end":
            live.extend(_events(ws.receive_text()))
        worker.join()
    assert live[0]["type"] == "run_start"
    assert live[0]["run_id"] != backlog[0]["run_id"]
    assert [e["seq"] for e in live] == list(range(len(live)))


def test_fallback_page_when_viewer_is_not_built(monkeypatch, tmp_path: Path) -> None:
    import agent_xray.server as server

    monkeypatch.setattr(server, "STATIC_DIR", tmp_path / "no-viewer")
    client = TestClient(create_app(EventBus(), lambda: None), base_url="http://localhost")
    page = client.get("/")
    assert page.status_code == 200 and "viewer has not been built" in page.text


def test_background_server(tmp_path: Path) -> None:
    session = Session()
    session.configure(record_dir=tmp_path)
    server = ViewerServer(create_app(session.bus, session.record_dir), port=0)
    url = server.start()
    try:
        assert server.is_running
        assert httpx.get(url + "/").status_code == 200
        with connect(f"ws://127.0.0.1:{server.port}/ws") as ws:
            worker = threading.Thread(target=_run_into, args=(session,))
            worker.start()
            events: list[dict] = []
            while not events or events[-1]["type"] != "run_end":
                events.extend(_events(ws.recv(timeout=10)))
            worker.join()
        assert events[0]["type"] == "run_start"
        assert events[-1]["data"]["status"] == "ok"
        runs = httpx.get(url + "/api/runs").json()
        assert [r["run_id"] for r in runs] == [events[0]["run_id"]]
    finally:
        server.stop()
    assert not server.is_running


def test_port_taken_uses_next_free_port() -> None:
    first = ViewerServer(create_app(EventBus(), lambda: None), port=0)
    first.start()
    try:
        second = ViewerServer(create_app(EventBus(), lambda: None), port=first.port or 0)
        second.start()
        try:
            assert second.port != first.port
        finally:
            second.stop()
    finally:
        first.stop()


def test_session_starts_the_viewer_once(tmp_path: Path) -> None:
    session = Session()
    session.configure(record_dir=tmp_path)
    url = session.start_viewer(port=0, open_browser=False, keep_alive=False)
    try:
        assert session.start_viewer(port=0, open_browser=False, keep_alive=False) == url
        assert httpx.get(url + "/api/runs").json() == []
        _run_into(session)
        assert [r["status"] for r in httpx.get(url + "/api/runs").json()] == ["ok"]
    finally:
        assert session.server is not None
        session.server.stop()


def test_watch_without_viewer_starts_no_server(monkeypatch, tmp_path: Path) -> None:
    # the package re-exports the watch() function under the module's name
    watch_module = importlib.import_module("agent_xray.watch")
    session = Session()
    monkeypatch.setattr(watch_module, "SESSION", session)
    graph = watch_module.watch(basic_fake.build_graph(), port=None, record_dir=tmp_path)
    graph.invoke(basic_fake.INPUT)
    assert session.server is None
    assert graph.last_recording is not None and graph.last_recording.is_file()


def test_websocket_with_a_foreign_host_is_refused() -> None:
    from starlette.testclient import WebSocketDenialResponse

    client = TestClient(create_app(EventBus(), lambda: None), base_url="http://localhost")
    attempt = client.websocket_connect("/ws", headers={"host": "evil.example"})
    with pytest.raises(WebSocketDenialResponse), attempt:
        pass


def test_foreign_hosts_are_rejected() -> None:
    """DNS rebinding: a page on evil.example resolving to 127.0.0.1 must not read recordings."""
    app = create_app(EventBus(), lambda: None)
    assert TestClient(app, base_url="http://evil.example").get("/api/runs").status_code == 400
    assert TestClient(app, base_url="http://127.0.0.1:7777").get("/api/runs").status_code == 200
    assert TestClient(app, base_url="http://localhost:7777").get("/api/runs").status_code == 200


def test_websocket_from_another_site_is_refused() -> None:
    import pytest
    from starlette.websockets import WebSocketDisconnect

    client = TestClient(create_app(EventBus(), lambda: None), base_url="http://localhost")
    foreign = {**LOCAL, "origin": "https://evil.example"}
    attempt = client.websocket_connect("/ws", headers=foreign)
    with pytest.raises(WebSocketDisconnect) as refused, attempt:
        pass
    assert refused.value.code == 1008  # policy violation
    # the viewer's own page (and non-browser clients without an Origin) are fine
    ok = {**LOCAL, "origin": "http://localhost:7777"}
    with client.websocket_connect("/ws", headers=ok) as ws:
        assert ws.receive_text()
    with client.websocket_connect("/ws", headers=LOCAL) as ws:
        assert ws.receive_text()
