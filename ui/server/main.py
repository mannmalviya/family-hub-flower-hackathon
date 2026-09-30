"""Local backend: the web UI talks to this, and this talks to the SuperLink."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from flwr.cli.chat.chat_app import (
    format_failure_event,
    parse_task_event,
    start_chat_run,
)
from flwr.cli.chat.chat_history import load_conversation
from flwr.cli.chat.chat_local_agent import build_local_agent
from flwr.cli.constant import CHAT_FAILURE_EVENTS, CHAT_TEXT_DELTA_EVENT
from flwr.cli.flower_config import read_superlink_connection
from flwr.cli.utils import init_http_client_from_connection
from flwr.proto.control_pb2 import (  # pylint: disable=E0611
    ListRunSeriesEventsRequest,
    ListRunSeriesRequest,
    ListRunsRequest,
    ShowFederationRequest,
)
from flwr.proto.runseries_pb2 import RunSeries  # pylint: disable=E0611

FEDERATION = "@lvl12tensorboi/family-hub"
AGENT_DIR = Path(__file__).resolve().parents[2] / "agent"

# Status lines shown while the lead agent calls Grid tools.
TOOL_STATUS = {
    "get_nodes": "Finding family nodes…",
    "push_messages": "Asking family nodes…",
    "pull_messages": "Waiting for replies…",
}
RUN_STATUS = {
    "pending": "Waiting in the SuperGrid queue…",
    "starting": "Starting the agent…",
    "running": "Thinking…",
}
# We poll instead of using StreamRunEvents: that stream has no read timeout,
# and its connection dies silently while a run waits in the queue.
POLL_SECONDS = 2

stub = init_http_client_from_connection(read_superlink_connection("supergrid"))
# Built once at startup. Restart the server after you change the agent.
local_agent = build_local_agent(AGENT_DIR)

app = FastAPI()


@app.get("/api/family")
def family() -> list[dict[str, str]]:
    res = stub.ShowFederation(ShowFederationRequest(federation_name=FEDERATION))
    return [
        {"name": node.name or str(node.node_id), "status": node.status}
        for node in res.federation.nodes
    ]


@app.get("/api/chats")
def chats() -> list[dict[str, str]]:
    res = stub.ListRunSeries(
        ListRunSeriesRequest(federation_id=FEDERATION, is_agent=True)
    )
    # Series ids are 64-bit, so send them as strings to keep JS from rounding.
    return [
        {
            "id": str(entry.series_id),
            "title": entry.description or "Untitled chat",
            "updated_at": entry.updated_at,
        }
        for entry in res.entries
    ]


@app.get("/api/chats/{series_id}")
def chat_messages(series_id: int) -> list[dict[str, str]]:
    entry = RunSeries(series_id=series_id, federation=FEDERATION)
    return [
        {"role": role, "text": text}
        for role, text in load_conversation(stub, entry, FEDERATION)
    ]


class ChatRequest(BaseModel):
    prompt: str
    series_id: str | None = None


def _sse(data: dict[str, str]) -> str:
    return f"data: {json.dumps(data)}\n\n"


def _stream_run(req: ChatRequest) -> Iterator[str]:
    try:
        run_id, series_id = start_chat_run(
            stub,
            req.prompt,
            FEDERATION,
            int(req.series_id) if req.series_id else None,
            local_agent.app_spec,
            local_agent.fab_hash,
            local_agent.fab_content,
        )
        yield _sse({"type": "series", "series_id": str(series_id)})
        seen: set[int] = set()
        last_status = ""
        while True:
            run = stub.ListRuns(ListRunsRequest(run_id=run_id)).run_dict[run_id]
            events = stub.ListRunSeriesEvents(
                ListRunSeriesEventsRequest(series_id=series_id)
            ).events
            for event in events:
                if event.run_id != run_id or event.id in seen:
                    continue
                seen.add(event.id)
                event_type, payload = parse_task_event(event)
                if event_type == CHAT_TEXT_DELTA_EVENT:
                    yield _sse({"type": "delta", "text": payload.get("delta", "")})
                elif event_type == "function_call":
                    status = TOOL_STATUS.get(payload.get("name", ""))
                    if status:
                        yield _sse({"type": "status", "text": status})
                elif event_type in CHAT_FAILURE_EVENTS:
                    yield _sse({"type": "error", "text": format_failure_event(payload)})
                    return
            if run.status.status == "finished":
                if run.status.sub_status != "completed":
                    reason = run.status.details or f"Run {run.status.sub_status}."
                    yield _sse({"type": "error", "text": reason})
                    return
                break
            status = RUN_STATUS.get(run.status.status, "")
            if status and status != last_status and not seen:
                last_status = status
                yield _sse({"type": "status", "text": status})
            time.sleep(POLL_SECONDS)
        yield _sse({"type": "done"})
    except Exception as exc:  # noqa: BLE001 - show any failure in the chat
        yield _sse({"type": "error", "text": str(exc) or type(exc).__name__})


@app.post("/api/chat")
def chat(req: ChatRequest) -> StreamingResponse:
    return StreamingResponse(_stream_run(req), media_type="text/event-stream")
