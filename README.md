# Brane Integrator

Policy-driven federated workflow generation for the [Brane](https://github.com/epi-project/brane) framework.

The Integrator sits between the **BraneHub** governance portal and the **Brane** execution engine. When a data collaboration project is approved in BraneHub, the Integrator automatically reads its policy configuration, generates a BraneScript workflow that enforces those policies, provisions ephemeral Brane worker nodes for each participating institution, executes the workflow, and posts results back to BraneHub. No researcher needs to write BraneScript manually.

---

## Table of contents

1. [What it does](#what-it-does)
2. [How the pipeline works](#how-the-pipeline-works)
3. [Design decisions](#design-decisions)
4. [Prerequisites](#prerequisites)
5. [Installing Brane correctly](#installing-brane-correctly)
6. [Node template (bundled certs)](#node-template-bundled-certs)
7. [Installation](#installation)
8. [Configuration (.env)](#configuration-env)
9. [Running](#running)
10. [Running with mock BraneHub](#running-with-mock-branehub)
11. [Admin dashboard](#admin-dashboard)
12. [Reset and wipe](#reset-and-wipe)
13. [Known Brane bugs and workarounds](#known-brane-bugs-and-workarounds)
14. [WSL2-specific notes](#wsl2-specific-notes)
15. [Known limitations](#known-limitations)

---

## What it does

Given a BraneHub project with participants, datasets, and policy fields filled in, the Integrator:

1. **Fetches project config from BraneHub** — participant nodes, datasets, package info, and policy fields (structured and free-text).
2. **Extracts policy claims from free-text** — privacy notes, data provenance, and source-of-truth fields are sent to an LLM in parallel. The LLM extracts structured claims (e.g. `identifiability=Pseudonymized`, `legal_basis=HIPAA TPO`) with confidence scores. Low-confidence claims are discarded.
3. **Interprets policies into BraneScript constructs** — claims are mapped to `#[on()]`, `#[tag()]`, and `#![wf_tag()]` annotations following the Kokash policy-to-construct framework.
4. **Generates a valid BraneScript workflow** — using either a deterministic template (map-reduce pattern) or an LLM with validate-and-retry. A 9-rule structural validator checks the output before it is saved.
5. **Provisions ephemeral Brane worker nodes** — each participant and coordinator gets a Docker-based Brane worker node spun up on demand. Nodes are torn down after the project completes.
6. **Executes the workflow and reports results** — runs the BraneScript via the Brane CLI, parses the output, and posts a completion callback (result or error) back to BraneHub.

A full **traceability report** is generated alongside every workflow, linking each BraneScript annotation back to the specific policy field or free-text claim that produced it.

---

## How the pipeline works

When BraneHub triggers a workflow generation for a project, the Integrator runs through the following stages in sequence, all within a single background task:

**1. Config parsing** — The raw project JSON from BraneHub is parsed into a structured `IntegratorConfig` object. This captures participant nodes, dataset names, the package to use, function names (local, combine, finalize), the coordinator node, and all policy fields.

**2. Free-text extraction** — Policy fields like `privacy_legal_notes`, `data_provenance`, and `source_of_truth` often contain unstructured prose written by researchers. These are sent to an LLM in parallel (one call per field) to extract structured claims — for example `identifiability=PseudonymizedBySource` or `legal_basis=HIPAA TPO` — each with a confidence score. Low-confidence claims are discarded.

**3. Policy interpretation** — Structured policy claims (from both typed fields and the free-text extraction above) are mapped to BraneScript constructs: `#[on("node")]` site annotations, `#[tag("key.value")]` per-call annotations, and `#![wf_tag("key.value")]` workflow-level tags. This follows the Kokash policy-to-construct framework.

**4. BraneScript generation** — The interpreted policies and workflow config are passed to either the `TemplateGenerator` (deterministic map-reduce) or the `LlmGenerator` (GPT-4o with validate-and-retry). Both produce a complete, runnable BraneScript.

**5. Package push + validation** — The package is pushed to the Brane central registry so the validator can query the GraphQL API to confirm function names exist. Then the 9-rule structural validator checks the BraneScript for correctness. A traceability report is generated, linking every annotation back to the policy source that produced it.

**6. Upload to BraneHub** — The validated script and traceability report are uploaded to BraneHub. The workflow enters `generated` status and awaits researcher approval.

**7. Execution** — When the researcher approves in BraneHub, a run callback arrives. The Integrator strips tag annotations (eFLINT bug workaround), writes the script to a temp file, and runs it via `brane workflow run`. The result is parsed and posted back to BraneHub as a completion callback.

**Module layout:**

| Path | Purpose |
|---|---|
| `main.py` | FastAPI app, startup lifecycle, WSL2 bridge init |
| `app/api/` | HTTP routers — `workflow.py`, `infra.py`, `packages.py`, `admin.py` |
| `app/application/workflow_generation/` | Core pipeline — config parser, free-text extractor, policy interpreter, validator, job handler |
| `app/application/workflow_generation/strategy/` | `template_generator.py` (deterministic) and `llm_generator.py` (LLM + retry) |
| `app/application/utils/` | `prompts.py` (all LLM prompt constants), `prompt_builder.py` |
| `app/application/node_provisioner/` | Spin up / tear down Brane worker nodes via Docker SDK + branectl |
| `app/application/package_manager/` | LLM-assisted Python package authoring and `brane package build/push` |
| `app/infrastructure/` | Settings, SQLite database, BraneHub HTTP client, OpenAI LLM service |
| `app/domain/` | SQLModel domain models (Workflow, PackageSource, BraneNode) |
| `app/templates/` | `node.yml.j2` — Jinja2 template rendered per provisioned node |
| `brane-node-template/` | Bundled TLS certs and worker config copied when provisioning nodes |
| `scripts/reset.sh` | Full teardown — wipes all managed nodes and databases |

---

## Design decisions

These explain *why* things work the way they do. Understanding them will save you hours of debugging.

### Single uvicorn worker (never run with `--workers N`)

The abort and dismissed-workflow handlers communicate with the execution handler via two module-level variables:

```python
_running_processes: dict[str, subprocess.Popen] = {}
_aborted_workflows: set[str] = set()
```

These are module-level because a separate `WorkflowJobHandler` instance is created per HTTP request. With multiple uvicorn workers, each worker process has its own copy of these variables — an abort request routed to worker 2 cannot reach the subprocess running in worker 1. Always run with a single worker.

### `Popen` instead of `subprocess.run` for workflow execution

`subprocess.run()` blocks until completion with no handle to the process. The Integrator uses `subprocess.Popen()` so that `handle_abort()` and `handle_dismissed()` can call `proc.terminate()` from a different HTTP request context. The process handle is stored in `_running_processes[workflow_id]` *before* `proc.communicate()` is called.

### Abort coordination ordering invariant

In `handle_abort()`, `_aborted_workflows.add(workflow_id)` **must execute before** `proc.terminate()`. After `proc.communicate()` returns, `handle_execution()` checks `proc.returncode < 0 AND workflow_id in _aborted_workflows` to decide whether the process was killed externally. Both conditions are required — a crash also produces a negative return code, and without the set membership check, a crash would be misreported as an abort.

### Tag stripping before Brane submission (eFLINT bug workaround)

The generated BraneScript includes `#[tag()]` and `#![wf_tag()]` annotations that represent data-flow policies. The Integrator generates these correctly per the Brane design spec, and they are preserved in the database and traceability report. However, they are stripped from the script before it is submitted to `brane workflow run` because of a serialisation bug in `brane-chk` (see [Bug F1](#bug-f1-eflint-tag-annotation-serialisation)). Every stripped annotation is recorded in the traceability report with a note explaining why.

### Pre-validation package push

The 9-rule validator's Rule 9 queries the Brane GraphQL API to verify that every function called in the generated BraneScript actually exists in the package registry. For this check to work, the package must already be pushed to the central node *before* validation runs. The Integrator pushes the package as part of the generation pipeline, before calling the validator.

### Two generation strategies

**`map_reduce` (default):** A deterministic Python template that produces a correct left-fold combine chain for any number of participants. Because the template is built from the config directly, Rules 1–8 of the validator cannot fail by construction. Use this unless you need the LLM's flexibility.

**`llm`:** Sends the full workflow context to GPT-4o and validates the output. If validation fails, it sends a retry prompt listing the failed rules. At most 2 LLM calls are made. The `container.yml` of the built package is included in the prompt so the LLM has exact function signatures and argument counts, which prevents Rule 8 (combine argument count) failures.

### Left-fold combine chain

The BraneScript `combine` function always takes exactly 2 arguments. For N participants the template chains N−1 combine calls:

```
acc_0 = combine(stats_1, stats_2)
acc_1 = combine(acc_0,   stats_3)
acc_2 = combine(acc_1,   stats_4)
result = acc_2
```

Each intermediate call gets its own `#[on("coordinator")]` annotation.

---

## Prerequisites

- **Python 3.11+**
- **Docker** — Docker Desktop on WSL2, or Docker Engine on native Linux
- **Brane CLI** — `brane` and `branectl` in your PATH (see [Installing Brane correctly](#installing-brane-correctly))
- **OpenAI API key** — required for LLM workflow generation and LLM-assisted package authoring

---

## Installing Brane correctly

The Integrator was developed and tested against **Brane 3.0.0-nightly (commit `7175fba8`)**. Brane is not yet on a stable release cycle — using a different commit may produce different behaviour, particularly around the eFLINT policy checker.

### Build from source

```bash
git clone https://github.com/epi-project/brane
cd brane
git checkout 7175fba8
cargo build --release
```

After building, `brane` and `branectl` will be at `target/release/brane` and `target/release/branectl`. Add them to your PATH or symlink them to `/usr/local/bin/`.

### Verify your install

```bash
# Both should print a version string without error
brane --version
branectl --version

# Docker must be running
docker ps
```

### The branelet binary

`branelet` is the in-container helper that runs package functions. **It must exactly match your `brane` CLI version.** A mismatch causes packages to hang or crash at runtime with no useful error message.

A pre-compiled x86-64 Linux `branelet` matching commit `7175fba8` ships at `bin/branelet` in this repository. Set `BRANELET_PATH` in your `.env` to its absolute path:

```bash
BRANELET_PATH=/absolute/path/to/brane-integrator/bin/branelet
```

If you built Brane from source, your matching `branelet` is at `target/release/branelet` in the brane repo.

**Why `--init branelet` matters:** Without it, `brane package build` picks up whatever `branelet` it finds on the system (or inside the base Docker image), which is almost always a version mismatch. This was the source of several hard-to-diagnose package execution failures during development.

### Start the central Brane node

Run this **once** on a fresh machine to generate certificates, node configs, and start the central containers:

```bash
branectl start central
```

Verify it worked:

```bash
docker ps | grep brane-
```

You should see `brane-api`, `brane-drv`, `brane-plr`, and `brane-prx` running. If any are missing, check `docker logs brane-api` for errors.

On WSL2, the central containers will go down every time Docker Desktop restarts (Windows reboot, Docker update). The Integrator handles this automatically when `WSL2_MODE=true` — see [WSL2-specific notes](#wsl2-specific-notes).

---

## Node template (bundled certs)

When the Integrator provisions a new participant or coordinator node, it needs TLS certificates and a base config to copy into the new node's directory. These are bundled in `brane-node-template/` in this repository — no manual setup is required.

```
brane-node-template/
  central-certs/       ← ca.pem, client-id.pem  (registered into central/certs/<node>/)
  worker-node/         ← certs/, backend.yml, proxy.yml, policies.db, policy secrets
```

**Important:** These are self-signed certs shared across all provisioned nodes. They satisfy Brane's TLS requirements in a local single-machine simulation only. **Do not use these in a production or multi-institution deployment** — each institution should generate its own certs with `branectl generate-certs`.

---

## Installation

```bash
# Clone the repo
git clone https://github.com/aditya-130/brane-integrator
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

All configuration is via environment variables in `.env`. Copy `.env.example` and fill it in.

**Required:**

| Variable | Description |
|---|---|
| `BRANE_INTEGRATOR_API_KEY` | Shared secret — all API clients must send this in `X-API-Key`. Generate with `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `BRANEHUB_BASE_URL` | Base URL of your BraneHub instance. Leave empty to run without BraneHub (standalone/mock mode) |
| `OPENAI_API_KEY` | Required for LLM workflow generation and LLM package authoring |
| `BRANE_NODES_DIR` | Absolute path to your Brane node directory (the one that contains `central/`) |
| `BRANE_DATA_DIR` | Absolute path to where Brane dataset files live |
| `BRANE_RESULTS_DIR` | Absolute path to where Brane writes workflow results |
| `BRANELET_PATH` | Absolute path to the `branelet` binary (see above) |

**Optional / tuning:**

| Variable | Default | Description |
|---|---|---|
| `WORKFLOW_GENERATION_STRATEGY` | `map_reduce` | `map_reduce` (deterministic template) or `llm` (GPT-4o with retry) |
| `OPENAI_MODEL` | `gpt-4o` | OpenAI model for all LLM calls |
| `BRANE_CLI_PATH` | `brane` from PATH | Absolute path to the `brane` CLI binary, if not on PATH |
| `BRANE_API_URL` | `localhost:50051` | Brane API address used by the workflow executor |
| `WSL2_MODE` | `false` | Set `true` on WSL2 — enables socat bridge and Docker Desktop PATH fix |
| `EXECUTION_TIMEOUT_SECONDS` | `600` | Seconds before workflow execution is killed |
| `BRANE_API_CONTAINER` | `brane-api` | Docker container name for the central brane-api |
| `BRANE_CENTRAL_PACKAGES_PATH` | `/packages` | Path inside brane-api container where packages are stored |
| `BRANE_PACKAGES_DIR` | `~/.local/share/brane/packages` | Local Brane package registry directory |
| `DATABASE_URL` | `sqlite:///./integrator.db` | SQLAlchemy database URL |
| `SQL_ECHO` | `false` | Log all SQL statements (debug only) |

---

## Running

```bash
source .venv/bin/activate

# Single worker — required (see Design decisions)
uvicorn main:app --reload --port 8000
```

On startup the Integrator:
- Creates the SQLite database and tables if they do not exist
- Resets any `generating` or `executing` workflows left over from a previous crash back to `pending`
- Reconciles provisioned nodes — restarts any stopped Docker containers
- **WSL2 only:** recreates stopped central Brane containers, rebuilds the `brane-fwd` socat bridge, patches `host.docker.internal` in central containers
- Starts a 60-second background loop to keep node containers healthy

The API docs are available at `http://localhost:8000/docs`.

---

## Running with mock BraneHub

For standalone testing without a real BraneHub deployment, a minimal mock is included in the sibling directory `../mock-branehub`.

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

In `.env`:
```
BRANEHUB_BASE_URL=http://localhost:5000
```

The mock BraneHub serves a hardcoded project config and receives completion callbacks, letting you test the full pipeline locally. Pre-built test project configs are in `app/mockdata/`.

---

## Admin dashboard

Open `http://localhost:8000/admin` in a browser.

The dashboard shows:
- All provisioned participant and coordinator nodes, with Docker container status and DB state
- All registered projects, with package build status and latest workflow cycle
- Forms to provision/deprovision nodes, register datasets manually, and push packages

The admin interface has **no authentication**. It is intended for local development use only. Do not expose port 8000 publicly.

---

## Reset and wipe

To tear down everything and start completely fresh:

```bash
bash scripts/reset.sh
```

This removes:
- All `participant-*` and `coordinator-*` Docker containers and Docker networks
- Their working directories under `BRANE_NODES_DIR`
- Their entries in `central/infra.yml`
- Their certificates from `central/certs/`
- `integrator.db`
- `mock_branehub.db` (if it exists in the sibling directory)

It does **not** touch the central Brane node or its containers.

After running, restart the Integrator (and mock BraneHub if using it). Both start with a clean slate.

**Note:** Packages built by the Integrator also live in the local Brane package registry (`BRANE_PACKAGES_DIR`) and in the central node's registry. These are not cleaned up by `reset.sh`. See [Bug F5](#bug-f5-stale-packages-survive-reset) below.

---

## Known Brane bugs and workarounds

These are bugs in Brane itself (not in the Integrator) that we hit during development. Each has a workaround implemented in the Integrator, documented here so the reasoning is clear.

---

### Bug F1: eFLINT tag annotation serialisation

**Symptom:** Workflows with `#[tag()]` or `#![wf_tag()]` annotations fail to plan with `"Failed to plan workflow"` and a gRPC error from `brane-chk`.

**Root cause:** The eFLINT base ontology defines `tag` as a 2-component fact:
```
Fact tag Identified by user * string.   (brane-chk/policy/metadata.eflint)
```
But the Rust serialiser in `brane-chk/src/workflow/eflint.rs:74` emits a 1-component assertion:
```
+tag("identifiability.Pseudonymized")   ← missing the user component
```
The eFLINT engine rejects this with `"elements of tag have 2 components, 1 given"`, which propagates as a planner failure.

**Workaround:** The Integrator strips all `#[tag()]` and `#![wf_tag()]` lines from the script before writing the temp file submitted to `brane workflow run`. The full annotated script is preserved in the database and in BraneHub. Every stripped annotation is recorded in the traceability report with a note: `"stripped before Brane submission (eFLINT bug workaround)"`.

---

### Bug F2: `brane package build` exits 0 on failure

**Symptom:** `brane package build` returns exit code 0 even when the Docker build fails, making it impossible to detect failure from the return code alone.

**Workaround:** The Integrator's `PackageBuilder` scans stdout for the string `"failed to build"` to detect failure, ignoring the exit code.

---

### Bug F3: `brane data build` registers datasets locally only

**Symptom:** Datasets registered with `brane data build` appear in the local CLI index but are not propagated to other nodes.

**Explanation:** In a real federated deployment, each participant institution runs `brane data build` on their own node to register their local dataset. The Brane CLI does not federate dataset registration. The Integrator's admin dashboard provides a simulation tool that runs `brane data build` locally on behalf of each participant for testing purposes only.

---

### Bug F4: `brane package push` fails when packages directory is owned by root

**Symptom:** `brane package push` fails with a permission error. On WSL2, Docker Desktop sometimes creates the central `packages/` directory as `root:root` inside the `brane-api` container.

**Workaround:** `PackageBuilder.push()` always runs `docker exec -u root brane-api chown brane:brane /packages` before every push.

---

### Bug F5: Stale packages survive `reset.sh`

**Symptom:** After a reset and rebuild, `brane package list` still shows old packages. If the package name matches, `brane package build` may silently reuse the cached image.

**Workaround:** After running `reset.sh`, manually clean the local registry:
```bash
brane package list
brane package remove <name> <version>
```
Also remove the package from the central node's packages directory if needed:
```bash
docker exec -u root brane-api rm -rf /packages/<name>
```

---

## WSL2-specific notes

Set `WSL2_MODE=true` in `.env` when running on WSL2 with Docker Desktop.

On native Linux, none of the following applies — leave `WSL2_MODE=false`.

---

### 1. Docker Desktop PATH extension

Docker Desktop on WSL2 puts its CLI tools at `/mnt/wsl/docker-desktop/cli-tools/usr/bin`, which is not always on PATH when the Integrator runs subprocesses. When `WSL2_MODE=true`, the Integrator prepends this path to `os.environ["PATH"]` for all subprocess calls.

---

### 2. Central container auto-restart

Docker Desktop restarts its daemon on every Windows reboot and after Docker updates. This stops all Brane central containers (`brane-api`, `brane-drv`, `brane-plr`, `brane-prx`). On startup, the Integrator detects stopped central containers and recreates them via the Docker SDK without losing any state (node configs and certs are on disk).

---

### 3. `brane-fwd` socat bridge

**The problem:** Brane's central containers run on the `brane-central` Docker network. Worker node containers run on their own `brane-worker-<node>` networks. On WSL2, Hyper-V port exclusions prevent direct cross-network connections, so the central containers cannot reach the worker containers via `host.docker.internal`.

**The workaround:** On startup, the Integrator creates a container called `brane-fwd` on the `brane-central` network running `alpine/socat`. For every provisioned worker node, `brane-fwd` gets a `socat` rule that forwards the node's service ports (reg, job, chk, prx) to the corresponding worker container. The Integrator then patches `/etc/hosts` in each central container to replace `host.docker.internal` with `brane-fwd`'s IP on the `brane-central` network.

The result is that central containers reach worker containers via `brane-fwd` as a proxy, bypassing the Hyper-V restriction.

This `brane-fwd` container is rebuilt on every Integrator startup to pick up any new worker nodes provisioned since the last restart.

**On native Linux:** Docker handles cross-network routing directly. `host.docker.internal` resolves correctly, and no bridge is needed.

---

## Known limitations

- **Local simulation only.** The `node.yml.j2` template hardcodes `host.docker.internal` as the external address for all worker services. This works when everything runs on one machine but breaks in a real multi-institution deployment where each node has its own IP. Production deployment would require generating `node.yml` with real external addresses and transferring node configs to remote machines via SSH/SCP (not currently implemented).

- **No real federated networking.** Node provisioning runs entirely on the local machine via Docker. Each "participant node" is a Docker container on the same host, not a remote server. The Integrator simulates federation, it does not implement it.

- **LLM generator retries once.** If the LLM-generated BraneScript fails validation twice, the Integrator reports a generation failure. The failed rules are included in the retry prompt to guide the model, but there is no third attempt.

- **Edited BraneScript in BraneHub is not used.** After the Integrator uploads a generated script to BraneHub, a researcher can edit it in BraneHub's review UI before approving. However, the `RunWorkflow` callback from BraneHub does not transmit the (potentially edited) script — it only carries a `script_version` identifier. The Integrator always executes the original script stored in its database. Edits made in the BraneHub UI are silently discarded.

- **Admin dashboard has no authentication.** The `/admin` interface and the `/api/...` routes protected only by `X-API-Key` are intended for local use. The API key is set in `.env` and included in the admin HTML source — do not expose port 8000 publicly.

- **Dataset registration is manual.** Researchers must register their datasets using the admin dashboard's dataset registration form before running a workflow. There is no automated dataset discovery.
