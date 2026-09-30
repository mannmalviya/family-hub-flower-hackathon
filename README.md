# family-hub

Directory Structure:
```
family-hub/
    ui/
    agentapp/
    deploy/
    .gitignore
    README.md
    PLAN.md
```

- agent/ needs its own pyproject.toml. Flower packages that folder as a unit. Keep the UI code out of it.
- ui/ has its own Node or Python setup, so the two do not mix.
- deploy/ holds the Docker setup. Each teammate runs it on their laptop.

```
family-hub/
  ui/              web app (runs outside Flower)
  agent/        AgentApp with its own pyproject.toml
    pyproject.toml
    family_hub/
      agent_app.py
      calendar_tool.py   calendar code, if it can live in the AgentApp
  deploy/
    compose.yaml         one SuperNode service for each laptop
  .gitignore             must list keys/ and token files
  README.md
  PLAN.md
```


This is our project for Flower hackathon @Stanford Sep29th 2026.

## Architecture

```mermaid
flowchart TB
    User["👤 User<br/>(flwr chat)"]

    subgraph Laptop["💻 One laptop (Docker) — demo setup"]
        direction TB

        subgraph SL["SuperLink container"]
            Lead["🧠 Lead Agent<br/>(AgentApp, lead copy)"]
            Link{{"SuperLink<br/>routes messages"}}
            Lead <--> Link
        end

        subgraph N1["Mann — SuperNode container"]
            A1["AgentApp<br/>(member copy)"]
            D1[("schedule.csv<br/>medical.csv")]
            A1 --> D1
        end

        subgraph N2["Bro — SuperNode container"]
            A2["AgentApp<br/>(member copy)"]
            D2[("schedule.csv<br/>medical.csv")]
            A2 --> D2
        end

        subgraph N3["Dad — SuperNode container"]
            A3["AgentApp<br/>(member copy)"]
            D3[("schedule.csv<br/>medical.csv")]
            A3 --> D3
        end

        subgraph N4["Mom — SuperNode container"]
            A4["AgentApp<br/>(member copy)"]
            D4[("schedule.csv<br/>medical.csv")]
            A4 --> D4
        end

        N1 <-->|"connects out"| Link
        N2 <-->|"connects out"| Link
        N3 <-->|"connects out"| Link
        N4 <-->|"connects out"| Link
    end

    LLM["☁️ LLM (gpt-5.6-sol)<br/>Flower model API"]

    User <--> Link
    Lead <-.->|"model calls<br/>via SuperLink"| LLM
```

## Web UI

The UI chats with the Family Hub agent on SuperGrid. It runs on your laptop only.

1. Log in once: `cd agent && uv run flwr login supergrid`
2. Start the backend: `cd ui/server && uv run uvicorn main:app --port 8000`
3. Start the page: `cd ui/web && npm install && npm run dev`
4. Open http://localhost:5173

The backend packs `agent/` when it starts. Restart it after you change the agent.
