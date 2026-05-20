# Brane Integrator
Policy-driven federated workflow generation for the Brane framework.

---

## Starting the system

Run each service in its own terminal.

**Terminal 1 — Mock BraneHub:**
```bash
cd ~/thesis/integrator/mock-branehub
source .venv/bin/activate
uvicorn main:app --reload --port 8100
```

**Terminal 2 — Integrator:**
```bash
cd ~/thesis/integrator/brane-integrator
source .venv/bin/activate
uvicorn main:app --reload --port 8000
```

The Integrator handles everything on startup automatically:
- Checks `brane-api` is running (logs critical if not — see Prerequisites)
- Rebuilds `brane-fwd` fresh and connects it to all provisioned nodes from DB
- Patches `host.docker.internal` in central containers to route through `brane-fwd`
- Restarts any provisioned node containers that are down
- Starts a 60 s background loop that keeps socat rules healthy mid-session

---

## Prerequisites (one-time setup only)

Run this once when setting up Brane for the first time on a new machine:

```bash
branectl start central
```

This generates certs, creates configs, and starts the central containers for the first time. After that you never need to run it again.

On every subsequent start the Integrator handles everything automatically — including recreating any central containers that went down due to WSL2 stale bind-mounts.

---

## Full reset (wipe everything and start fresh)

```bash
bash scripts/reset.sh
```

Removes all participant and coordinator nodes — containers, Docker networks, working directories, `infra.yml` entries, central certs, `integrator.db`, and `mock_branehub.db`. Does not touch static Brane nodes (alice, bob, worker1, etc.) or the central node.

After running: restart mock BraneHub and the Integrator. Both start with a completely clean slate.

---

## Environment variables

Copy `.env.example` to `.env` and fill in:

| Variable | Description |
|---|---|
| `BRANE_INTEGRATOR_API_KEY` | Shared secret for all API calls |
| `BRANEHUB_BASE_URL` | Set to `http://localhost:8100` for mock BraneHub |
| `OPENAI_API_KEY` | Required for LLM package generation and workflow generation |
| `WORKFLOW_GENERATION_STRATEGY` | `map_reduce` (deterministic) or `llm` |
| `BRANE_API_URL` | Brane GraphQL endpoint, default `localhost:50051` |
| `BRANELET_PATH` | Path to cached branelet binary — required for `brane package build` |
