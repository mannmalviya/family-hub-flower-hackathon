"""A minimal Flower AgentApp."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any

from flwr.agentapp import AgentApp, AgentSession
from flwr.app import Context
from flwr.common.constant import SUPERLINK_NODE_ID

MODEL = "openai/gpt-5.6-sol"

app = AgentApp()


def _message_text(content: Any) -> str:
    """Extract text from a trace message."""
    if isinstance(content, str):
        return content
    parts = []
    for part in content:
        text = part.get("text", part.get("refusal"))
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts)


def _conversation(agent: AgentSession, context: Context) -> list[dict[str, str]]:
    """Rebuild user and assistant messages from this run series."""
    run_order: list[int] = []
    turns_by_run: dict[int, list[dict[str, str]]] = {}
    assistant_parts_by_run: dict[int, list[str]] = {}
    current_prompt_seen = False
    for event in agent.events.get_trace():
        run_id = event.get("run_id")
        event_type = event.get("event")
        data = event["data"]
        if not isinstance(run_id, int):
            continue

        if event_type == "message" and data.get("role") == "user":
            assistant_parts_by_run.pop(run_id, None)
            text = _message_text(data["content"])
            if run_id not in turns_by_run:
                run_order.append(run_id)
            turns_by_run[run_id] = [
                {"type": "message", "role": "user", "content": text}
            ]
            current_prompt_seen |= (
                run_id == context.run_id and text.strip() == agent.prompt.strip()
            )
        elif event_type in {
            "response.output_text.delta",
            "response.refusal.delta",
        }:
            delta = data.get("delta")
            if isinstance(delta, str):
                assistant_parts_by_run.setdefault(run_id, []).append(delta)
        elif event_type == "response.completed":
            assistant_parts = assistant_parts_by_run.pop(run_id, [])
            turn = turns_by_run.get(run_id)
            if assistant_parts and turn is not None:
                turn.append(
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": "".join(assistant_parts),
                    }
                )
        elif event_type in {"error", "response.failed", "response.incomplete"}:
            assistant_parts_by_run.pop(run_id, None)

    messages = [message for run_id in run_order for message in turns_by_run[run_id]]
    if not current_prompt_seen:
        messages.append(
            {"type": "message", "role": "user", "content": agent.prompt.strip()}
        )
    return messages


LEAD_INSTRUCTIONS = """You are the Family Hub assistant.
Today is {today}.
The family is Mann, Bro, Dad and Mom. Each one is a SuperNode named after them.
To answer a question about schedules or medical appointments:
1. Call get_nodes with sample_size null.
2. Call push_messages once, with one message per node the question is about,
   carrying the user's question. Ask every node if the question is about the
   whole family.
3. Call pull_messages with all returned message ids and timeout 120.
Each reply starts with the family member's name, then their schedule.csv and
medical.csv. Free time is any time not covered by a schedule or medical entry.
Always set reply_to_message_id to null. Never reply to a reply.
After pull_messages returns the replies, stop calling tools and answer the user.
Answer only from the replies. Never guess a schedule."""

DATA_DIR = Path("/data")


def _run_on_supernode(agent: AgentSession, context: Context) -> None:
    """Reply with this family member's name and their CSV files."""
    parts = [f"Name: {context.node_config['name']}"]
    for csv_path in sorted(DATA_DIR.glob("*.csv")):
        parts.append(f"--- {csv_path.name} ---\n{csv_path.read_text()}")
    answer = "\n".join(parts)
    agent.grid.call(
        {
            "name": "push_reply_message",
            "call_id": "reply",
            "arguments": {"payload": answer},
        }
    )
    print(answer)


def _run_lead(agent: AgentSession, context: Context) -> None:
    """Ask the model, and let it query family members through the Grid."""
    # Imported here so SuperNodes can run without installing openai.
    from openai import OpenAI

    client = OpenAI(
        base_url=os.environ["FLWR_RUNTIME_BASE_URL"],
        api_key=os.environ["FLWR_RUNTIME_API_KEY"],
        max_retries=0,
    )
    tools = agent.grid.tools()
    items: list[Any] = list(_conversation(agent, context))

    while True:
        stream = client.responses.create(
            model=MODEL,
            instructions=LEAD_INSTRUCTIONS.format(
                today=date.today().strftime("%A %Y-%m-%d")
            ),
            input=items,
            tools=tools,
            stream=True,
        )
        output_text = []
        output_items: list[dict[str, Any]] = []
        for event in stream:
            agent.events.emit(event.to_dict())
            if event.type in {"error", "response.failed"}:
                raise RuntimeError(f"Model response failed: {event}")
            if event.type == "response.output_text.delta":
                output_text.append(event.delta)
            if event.type == "response.completed":
                output_items = [item.to_dict() for item in event.response.output]

        tool_calls = [item for item in output_items if item["type"] == "function_call"]
        if not tool_calls:
            print("".join(output_text))
            return
        items += output_items
        items += [agent.grid.call(tool_call) for tool_call in tool_calls]


@app.main()
def main(agent: AgentSession, context: Context) -> None:
    """Run as the lead agent on the SuperLink, or as a family member's SuperNode."""
    if context.node_id == SUPERLINK_NODE_ID:
        _run_lead(agent, context)
    else:
        _run_on_supernode(agent, context)
