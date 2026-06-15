# Brane Integrator

Policy-driven federated workflow generation for the [Brane](https://github.com/epi-project/brane) framework. The Integrator bridges the BraneHub governance portal with the Brane execution engine: it reads project policies, generates a BraneScript workflow, provisions participant nodes, and drives execution end-to-end.

---

## Table of contents

1. [What it does](#what-it-does)
2. [Architecture overview](#architecture-overview)
3. [Prerequisites](#prerequisites)
4. [First-time Brane setup](#first-time-brane-setup)
5. [Template worker node](#template-worker-node)
6. [The branelet binary](#the-branelet-binary)
7. [Installation](#installation)
8. [Configuration (.env)](#configuration-env)
9. [Running](#running)
10. [Admin dashboard](#admin-dashboard)
11. [Reset and wipe](#reset-and-wipe)
12. [Known Brane quirks](#known-brane-quirks)
13. [WSL2-specific notes](#wsl2-specific-notes)

---

## What it does

1. Fetches project and policy data from BraneHub via its REST integration API.
2. Extracts structured policy claims from free-text fields using parallel LLM calls.
3. Maps those claims to BraneScript constructs (data-flow restrictions, site annotations, workflow tags) following the Kokash policy-to-construct framework.
4. Generates a valid BraneScript workflow using either a deterministic map-reduce strategy or an LLM with validate-and-retry.
5. Provisions ephemeral Brane worker nodes for each participant and coordinator.
6. Executes the workflow, streams results back, and posts a completion callback to BraneHub.

---

## Architecture overview

```
BraneHub (governance)
       │  REST /api/integration/*
       ▼
Brane Integrator  (this repo, FastAPI + SQLite)
       │  branectl / Docker SDK / GraphQL
       ▼
Brane central node  ──►  Brane worker nodes (dynamically provisioned)
```

Key modules:

| Path | Purpose |
|---|---|
| `main.py` | FastAPI app, startup lifecycle, WSL2 bridge init |
| `app/api/` | HTTP routers (infra, workflow, packages, admin) |
| `app/application/` | Workflow generation, node provisioner, package manager, prompts |
| `app/infrastructure/` | Settings, database, BraneHub HTTP client |
| `app/domain/` | SQLModel domain models |
| `scripts/reset.sh` | Full teardown — wipes all managed nodes and databases |

---

## Prerequisites

- **Python 3.11+**
- **Docker** (Docker Desktop on WSL2, or Docker Engine on native Linux)
- **Brane CLI** — `brane` and `branectl` in your PATH
  - Install: follow https://github.com/epi-project/brane — build from source or use a release binary
  - Tested with Brane `v2.0.0-beta`
- **OpenAI API key** — required for LLM workflow generation and package authoring features

---

## First-time Brane setup

Run this **once** on a new machine to generate certificates, node configs, and start the central containers:

```bash
branectl start central
```

After that, you never need to run it again. On WSL2, the Integrator automatically recreates central containers that go down when Docker Desktop restarts (see [WSL2-specific notes](#wsl2-specific-notes)).

Verify the central node is running:

```bash
docker ps | grep brane-
```

You should see `brane-api`, `brane-drv`, `brane-plr`, and `brane-prx` containers.

---

## Template worker node

The node provisioner copies an existing worker node directory to create participant and coordinator nodes. You must create one template node before the Integrator can provision anything.

```bash
# Create a worker node called "worker1" (the default template name)
branectl start worker --name worker1
```

This generates `$BRANE_NODES_DIR/worker1/` with the node config, certs, and data directories. The Integrator copies this directory for every new participant/coordinator it provisions.

If you change the template node name, set `BRANE_TEMPLATE_NODE` in `.env`.

---

## The branelet binary

Brane uses a helper binary called `branelet` to run package functions inside containers. The version bundled with a Brane release must exactly match the version of your `brane` CLI — a mismatch silently produces packages that hang or crash at runtime with no useful error.

**The correct binary for the version tested with this project is included at `bin/branelet`.**

You need to tell the Integrator where to find it via `BRANELET_PATH` in `.env`. It is passed to `brane package build --init <path>` every time a package is built.

```bash
# Absolute path to the binary in this repo:
BRANELET_PATH=/path/to/brane-integrator/bin/branelet
```

If you are using a different Brane version, replace `bin/branelet` with the matching binary from your Brane installation (typically at `~/.local/share/brane/branelet` after building from source).

**Why this matters:** Without `--init branelet`, `brane package build` uses whatever `branelet` it finds on the system, which may be outdated or missing. This was the source of many hard-to-diagnose package execution failures during development.

---

## Installation

```bash
# Clone and enter the repo
git clone <repo-url> brane-integrator
cd brane-integrator

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy and fill in the config
cp .env.example .env
$EDITOR .env
```

---

## Configuration (.env)

All configuration is via environment variables. Copy `.env.example` to `.env` and edit it.

**Required variables:**

| Variable | Description |
|---|---|
| `BRANE_INTEGRATOR_API_KEY` | Shared secret — all API clients must send this in `X-API-Key` |
| `BRANEHUB_BASE_URL` | URL of your BraneHub instance (empty = standalone mode) |
| `OPENAI_API_KEY` | Required for LLM features |
| `BRANE_NODES_DIR` | Absolute path to your Brane node configs directory |
| `BRANE_DATA_DIR` | Absolute path to where Brane dataset files live |
| `BRANE_RESULTS_DIR` | Absolute path to where Brane writes workflow results |
| `BRANELET_PATH` | Absolute path to the `branelet` binary (see above) |

**Key optional variables:**

| Variable | Default | Description |
|---|---|---|
| `WORKFLOW_GENERATION_STRATEGY` | `map_reduce` | `map_reduce` (deterministic) or `llm` |
| `BRANE_TEMPLATE_NODE` | `worker1` | Template node name under `BRANE_NODES_DIR` |
| `WSL2_MODE` | `false` | Set `true` on WSL2 — enables socat bridge and Docker Desktop PATH |
| `EXECUTION_TIMEOUT_SECONDS` | `600` | Max seconds to wait for a workflow result |
| `SQL_ECHO` | `false` | Log all SQL queries (debug only) |

See `.env.example` for the full list with comments.

---

## Running

```bash
# Activate venv if not already active
source .venv/bin/activate

# Start the Integrator
uvicorn main:app --reload --port 8000
```

On startup the Integrator:
- Initialises the SQLite database (creates tables if absent)
- On WSL2: recreates any stopped central containers, rebuilds the `brane-fwd` socat bridge, and patches `/etc/hosts` in central containers
- Resets any stuck `generating`/`executing` workflows to `pending`
- Reconciles provisioned nodes (restarts stopped containers)
- Starts a 60 s background loop to keep node state healthy

**With the mock BraneHub** (for standalone testing):

```bash
# Terminal 1 — mock BraneHub
cd ../mock-branehub
source .venv/bin/activate
uvicorn main:app --reload --port 5000

# Terminal 2 — Integrator
cd ../brane-integrator
source .venv/bin/activate
uvicorn main:app --reload --port 8000
```

Set `BRANEHUB_BASE_URL=http://localhost:5000` in `.env`.

---

## Admin dashboard

Open `http://localhost:8000/admin` in a browser.

The dashboard shows:
- All provisioned participant and coordinator nodes with Docker and DB status
- All registered projects with package build status and latest workflow cycle
- Forms to provision/deprovision nodes manually, register datasets, and push packages

The admin interface has no authentication — it is intended for local use only. Do not expose port 8000 publicly.

---

## Reset and wipe

To tear down all Integrator-managed nodes and start completely fresh:

```bash
bash scripts/reset.sh
```

This removes:
- All `participant-*` and `coordinator-*` Docker containers and networks
- Their working directories under `BRANE_NODES_DIR`
- Their entries in `central/infra.yml`
- Their certificates in `central/certs/`
- `integrator.db`
- `mock_branehub.db` (if it exists next to this repo)

It does **not** touch the static Brane nodes (worker1, central) or the central node containers.

After running, restart the Integrator (and mock BraneHub if using it). Both start with a clean slate.

---

## Known Brane quirks

These are issues we hit during development that are not obvious from the Brane documentation.

### branelet must match your Brane version exactly

Using a mismatched `branelet` causes packages to fail at runtime with cryptic errors. Always pass `--init <path>` to `brane package build`. See [The branelet binary](#the-branelet-binary).

### `brane package build` returns exit code 0 on failure

The CLI exits 0 even when the Docker build fails. The Integrator detects this by scanning stdout for `"failed to build"`. If you are calling `brane package build` manually, always read stdout carefully.

### `brane data build` registers datasets in a local index only

Datasets are registered per-machine. In a real federated deployment, each participant registers their own dataset on their own node. The Integrator's admin dashboard includes a simulation tool for local testing that runs `brane data build` on behalf of a participant.

### eFLINT tag annotations are stripped before execution

`#[tag()]` and `#![wf_tag()]` annotations in generated BraneScript are currently stripped by the `brane-chk` serializer due to a bug in the 2-component fact assertion format. The Integrator generates them for traceability and policy-completeness, and they appear correctly in the generated `.bs` file, but they do not influence execution. This is a known upstream bug (tracked as F1 in the thesis).

### Stale packages survive `reset.sh`

`brane package list` and `brane package remove` operate on the local CLI package registry. After a reset, old packages may still appear there. Run `brane package list` and remove them manually if needed, or the Integrator's package build step will silently reuse the cached image.

### `brane package push` requires the central packages directory to be chown'd

On WSL2, Docker Desktop bind-mounts can create the central `packages/` directory as `root:root` inside the container, making HTTP push fail. The Integrator's `PackageBuilder.push()` automatically runs `docker exec -u root brane-api chown brane:brane /packages` before each push.

---

## WSL2-specific notes

Set `WSL2_MODE=true` in `.env` when running on WSL2 with Docker Desktop.

**What this enables:**

1. **Docker Desktop PATH extension** — adds `/mnt/wsl/docker-desktop/cli-tools/usr/bin` to PATH so `docker` is available in subprocesses.

2. **Central container auto-restart** — Docker Desktop restarts its daemon on every Windows reboot, which invalidates bind-mount tokens and stops all Brane containers. The Integrator detects stopped central containers and recreates them on startup without losing state.

3. **brane-fwd socat bridge** — Brane's central containers cannot reach worker node containers across Docker network boundaries on WSL2 (Hyper-V port exclusions block direct connections). The Integrator creates a container called `brane-fwd` on the `brane-central` Docker network and runs `socat` rules inside it to forward traffic to each worker node. It patches `host.docker.internal` in each central container's `/etc/hosts` to point to `brane-fwd`'s IP instead of the Windows host.

On native Linux, none of this is needed — `branectl` manages the Brane containers and Docker networking works directly. Leave `WSL2_MODE=false`.
