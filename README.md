# family-hub

Directory Structure:
```
family-hub/
    ui/
    agentapp/
    deploy/
```

- agentapp/ needs its own pyproject.toml. Flower packages that folder as a unit. Keep the UI code out of it.
- ui/ has its own Node or Python setup, so the two do not mix.
- deploy/ holds the Docker setup. Each teammate runs it on their laptop.

This is our project for Flower hackathon @Stanford Sep29th 2026.
