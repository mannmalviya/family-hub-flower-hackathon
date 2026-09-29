"""A minimal Flower AgentApp."""

from __future__ import annotations

import os
from typing import Any

from flwr.agentapp import AgentApp, AgentSession
from flwr.app import Context
from flwr.common.constant import SUPERLINK_NODE_ID
from openai import OpenAI

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
Each family member is a SuperNode. Its name is the family member's name.
To answer a question about someone's schedule:
1. Call get_nodes to find the family member's node id.
2. Call push_messages to send your question to that node.
3. Call pull_messages with the returned message ids and timeout 120.
Always set reply_to_message_id to null. Never reply to a reply.
After pull_messages returns the replies, stop calling tools and answer the user.
Answer only from the replies. Never guess a schedule."""


def _run_on_supernode(agent: AgentSession, context: Context) -> None:
    """Answer a question from the lead agent. Step 1: fixed test reply."""
    answer = f"Test reply from node {context.node_id}: I am free all day."
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
            instructions=LEAD_INSTRUCTIONS,
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
