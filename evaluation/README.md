# Reproducing the evaluation

This folder contains the inputs, scripts, generated files, and recorded results
used in the thesis evaluation.

Use this commit when comparing your results with the thesis:

- Integrator commit: `04dbaaaa51578bb477384d5068426fd390e33ca0`
- Brane version: `3.0.0-nightly+7175fba8`
- [Fixed evaluation files](https://github.com/aditya-130/brane-integrator/tree/04dbaaaa51578bb477384d5068426fd390e33ca0/evaluation)
- [Current evaluation branch](https://github.com/aditya-130/brane-integrator/tree/evaluation/evaluation)

The commit link is the fixed reference. The branch link may change when new
commits are added.

## Before you start

Run the scripts from the repository root in WSL2 or Linux.

Be aware that:

- the scripts overwrite files in `evaluation/results/`;
- the LLM tests require an OpenAI API key and cost money;
- the live tests build and push packages to your local Brane setup;
- a new LLM run may differ from the recorded run;
- the live setup uses three logical Brane worker nodes plus the Brane central
  services on one physical machine. It is not a deployment across three real
  organisations.

If you want to keep the recorded results, copy them before running the scripts.

## Environment used

| Item | Value |
|---|---|
| Integrator | Branch `evaluation`, commit `04dbaaaa51578bb477384d5068426fd390e33ca0` |
| Brane | `3.0.0-nightly+7175fba8` |
| Platform | WSL2 with Docker Desktop on one physical machine |
| Brane worker nodes | `coordinator-1`, `participant-1`, and `participant-3` |
| Python | Python 3.11 or newer; the current WSL setup uses Python 3.12.3 |
| OpenAI model | `gpt-4o` through the Chat Completions API |
| Main LLM tests | Five runs per input |
| Extensibility test | Three runs |

The code does not set a seed, temperature, maximum token count, or dated model
snapshot. The exact Docker Desktop version and installed versions of
lower-bounded Python packages were not saved at the time of the evaluation.

## Where everything is

| What you need | Location |
|---|---|
| Eight governance scenarios | `app/mockdata/scenario_1.json` to `scenario_8.json` |
| Scenario workflow settings | `evaluation/fixtures/scenarios.json` |
| Free-text extraction gold set | `evaluation/gold_set.json` |
| Package-generation tasks | `evaluation/package_descriptions.json` |
| Ten invalid workflows | `evaluation/fault_injection/` |
| Test datasets | `evaluation/datasets/` |
| Reviewed reference packages | `evaluation/packages/` |
| Evaluation scripts | `evaluation/scripts/` |
| Recorded results | `evaluation/results/` |
| LLM prompts | `app/application/utils/prompts.py` |
| Prompt assembly | `app/application/utils/prompt_builder.py` |
| Branelet binary | `bin/branelet` |

## Which script produces which result

| Test | Run this | Main input | Compare with |
|---|---|---|---|
| Governance traceability | `evaluation/scripts/verify_traceability.py` | Eight governance scenarios | `evaluation/results/traceability_metrics.json` |
| Traceability regression checks | `evaluation/scripts/test_traceability_coverage.py` | Test cases inside the script | Console output |
| Invalid-workflow detection | `evaluation/scripts/evaluate_fault_injection.py` | `evaluation/fault_injection/` | `evaluation/results/fault_injection_results.json` |
| Template versus LLM generation | `evaluation/scripts/evaluate_generators.py` | Eight governance scenarios | `evaluation/results/comparison_table.json` |
| Structural extensibility | `evaluation/scripts/evaluate_extensibility.py` | K-means example inside the script | `evaluation/results/extensibility_results.json` |
| Live five-package evaluation | `evaluation/scripts/prepare_evaluation.py`, then `run_evaluation.py` | Reviewed packages and datasets | `evaluation/results/prepare_summary.json` and `e2e_results.json` |
| Free-text extraction | `evaluation/scripts/evaluate_extraction.py` | `evaluation/gold_set.json` | `evaluation/results/extraction_metrics.json` |
| Centralized references | `evaluation/scripts/centralized_baseline.py` | Reviewed packages and pooled datasets | `evaluation/results/baseline_pkg_1.json` to `baseline_pkg_5.json` |
| Path A package generation | `evaluation/scripts/evaluate_package_generation.py` | `evaluation/package_descriptions.json` | `evaluation/results/package_generation_results.json` |
| Path A consistency | `evaluation/scripts/m413_ast_jaccard.py` | Generated Path A packages | `evaluation/results/m413_ast_comparison.json` |
| Path B manifest generation | `evaluation/scripts/run_pathb_container_yml.py` | Reviewed package code | `evaluation/results/pathb_container_yml_results.json` |

`evaluation/scripts/evaluate_packages.py` and
`evaluation/results/package_metrics.json` are older supporting checks. Use
`prepare_evaluation.py` and `run_evaluation.py` for the final five-package
execution results reported in the thesis.

## Set up the Python environment

From the repository root, run:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

Copy `.env.example` to `.env`, then set the values needed for the test you want
to run:

```dotenv
BRANE_INTEGRATOR_API_KEY=eval
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4o
BRANE_API_URL=localhost:50051
BRANE_CLI_PATH=/absolute/path/to/brane
BRANELET_PATH=/absolute/path/to/brane-integrator/bin/branelet
BRANE_NODES_DIR=/absolute/path/to/brane/nodes
BRANE_DATA_DIR=/absolute/path/to/brane/data
BRANE_RESULTS_DIR=/absolute/path/to/brane/results
BRANE_PACKAGES_DIR=/absolute/path/to/brane/packages
WSL2_MODE=true
```

Do not commit `.env` or your OpenAI API key. See the root `README.md` for the
full Brane setup.

## Run the tests

Start with the tests that do not call an LLM or a live Brane instance:

```bash
python3 evaluation/datasets/generate_datasets.py
python3 evaluation/scripts/centralized_baseline.py
python3 evaluation/scripts/test_traceability_coverage.py
```

Run the LLM tests after adding `OPENAI_API_KEY` to `.env`:

```bash
python3 evaluation/scripts/evaluate_extraction.py
python3 evaluation/scripts/verify_traceability.py
python3 evaluation/scripts/evaluate_extensibility.py
python3 evaluation/scripts/evaluate_package_generation.py
```

For the live tests, start the Brane central services and all three logical
nodes first. Then run:

```bash
python3 evaluation/scripts/prepare_evaluation.py
python3 evaluation/scripts/evaluate_fault_injection.py
python3 evaluation/scripts/evaluate_generators.py
python3 evaluation/scripts/run_evaluation.py
python3 evaluation/scripts/evaluate_package_generation.py --build
```

`prepare_evaluation.py` builds and pushes the five reviewed packages, registers
the datasets, and generates the template and LLM workflows. `run_evaluation.py`
executes those workflows and compares their outputs with the centralized
results.

## Results you should compare against

| Test | Recorded result |
|---|---|
| Governance traceability | 324/324 expected source fields covered; line verifiability 1.0 |
| Invalid-workflow detection | 10/10 invalid workflows caught |
| Template versus LLM generation | First-pass validity 1.0 for both; LLM Jaccard consistency 0.8048 |
| Structural extensibility | Template 0/3 properties; LLM 3/3 in all three runs; not executed in Brane |
| Live execution | Template 5/5 packages; LLM 4/5 packages |
| Free-text extraction | Precision 0.8222, recall 0.9333, F1 0.8407, Jaccard 0.9444 |
| Path A generation | Schema validity 1.0, type accuracy 1.0, hallucination rate 0.16, raw numerical match 14/20 when excluding the single-participant task |
| Path A build and push | 5/5 representative builds and 5/5 pushes |
| Path A consistency | AST Jaccard 0.9412; raw-line Jaccard 0.4573 |
| Path B manifests | 25/25 schema-valid; Jaccard consistency 1.0 |

## Important notes about the recorded files

`evaluation/results/evaluation_report.json` was put together manually from the
individual test results and live execution notes. No single script generates
this file.

`evaluation/results/package_generation_results.json` was generated by the Path
A script and later updated with the representative build/push results and the
manual numerical-error classification. Running the script again will not
recreate those manually added fields.

The governance tag annotations are recorded metadata, not demonstrated runtime
controls. Before a workflow is submitted to Brane, the Integrator removes
`#[tag(...)]` and `#![wf_tag(...)]` because Brane and eFLINT use incompatible
metadata representations. Placement annotations remain in the executable
workflow.

## Known problems when rerunning the evaluation

- `evaluation/scripts/m413_ast_jaccard.py` and
  `evaluation/scripts/run_pathb_container_yml.py` contain the original path
  `/home/aditya/thesis/integrator/brane-integrator`. Change that path to your
  clone location before running them.
- `openai>=1.0.0`, `docker>=7.0.0`, and `python-dotenv>=1.0.0` are not exact
  version pins.
- `gpt-4o` is a moving model name, so new LLM output may differ.
- Live results depend on the state of Docker, the Brane registry, certificates,
  datasets, and WSL2 networking.
- These tests show what happened in the local prototype. They do not prove
  general legal compliance, privacy guarantees, or successful deployment
  across real organisations.
