# Eval kit for vendors selling RL environments to xAI

This guide is meant for vendors interested in selling RL environments to xAI. It walks you through everything you need to run the evaluation and submit your results. Please follow each step carefully — submissions that do not follow this format cannot be processed.

---

## What you will be doing

You will run three frontier coding models on the samples you wish to submit for consideration using [Harbor](https://github.com/harbor-framework/harbor), an open evaluation framework. Harbor runs each model inside an isolated Docker container, scores its output automatically, and records a full trace of the agent's actions. You then collect and submit those results using the library available here `vendor-eval`.

The three models to evaluate are:

| Model | Provider flag |
|-------|---------------|
| Claude Opus 4.6 | `anthropic/claude-opus-4-6` |
| GPT-5.3 Codex | `openai/gpt-5.3-codex` |
| Grok-4.20 Beta | `xai/grok-4.20-beta` (or `xai/grok-4`) |

**All three must be included in a single submission.**

---

## Prerequisites

Before starting, make sure you have the following installed and configured.

### 1. Docker

Harbor runs each task in an isolated Docker container. Docker must be running on the machine where you execute the evaluation.

- Download: https://docs.docker.com/get-docker/
- Verify it works: `docker run --rm hello-world`

### 2. Harbor

```bash
uv tool install harbor
```

Or with pip:

```bash
pip install harbor
```

Full Harbor documentation: https://harborframework.com/docs

### 3. This tool

```bash
uv tool install git+https://github.com/xai-org-shared/vendor-eval-kit.git
```

Or, if you have already cloned the repository:

```bash
uv tool install .
```

Or with pip (in an active virtual environment):

```bash
pip install git+https://github.com/xai-org-shared/vendor-eval-kit.git
```

### 4. API keys

You will need all three of the following keys exported in your shell before running the evaluation:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
export XAI_API_KEY="xai-..."
```

These keys are used by Harbor to call the respective model APIs. Ensure all three are set — the run will fail for any model whose key is missing.

---

## Step 1 — Make sure you have the sample task dataset you wish to submi

Your task format would look something like this:

```
coding-eval-tasks/
  task-1/
    environment/Dockerfile
    task.toml
    tests/
  task-2/
    ...
```

Note the full path to this directory — you will need it in the next step.

---

## Step 2 — Run the evaluation

Run the following command from any working directory. Replace `/path/to/coding-eval-tasks` with the actual path to your downloaded dataset.

```bash
harbor run \
  -p /path/to/coding-eval-tasks \
  -m anthropic/claude-opus-4-6 \
  -m openai/gpt-5.3-codex \
  -m xai/grok-4.20-beta \
  -a opencode \
  -k 4 \
  --job-name vendor-eval \
  --jobs-dir eval_results
```

**What each flag does:**

| Flag | Description |
|------|-------------|
| `-p <path>` | Path to the task dataset directory |
| `-m <model>` | Model to evaluate — all three must be included |
| `-a opencode` | The coding agent to use — do not change this |
| `-k 4` | Number of independent attempts per task — do not change this |
| `--job-name vendor-eval` | Name for this run — do not change this |
| `--jobs-dir eval_results` | Directory where results are written |

Harbor will pull and build Docker images, run each task, and write results into `eval_results/vendor-eval/`. This may take some time depending on the number of samples and machine. 

You can watch progress in the terminal. If a task fails partway through, Harbor records the failure and continues with the remaining tasks — you do not need to restart from scratch.

### Speeding up the evaluation with cloud sandboxes

If you want to significantly reduce total wall-clock time, Harbor supports running tasks in parallel on cloud sandboxes:

**https://harborframework.com/docs/run-jobs/cloud-sandboxes**

Cloud sandboxes distribute tasks across many machines simultaneously rather than running them sequentially on one machine. Setup takes around 15 minutes and can reduce total eval time from several hours to under 30 minutes. This is strongly recommended for large datasets.

---

## Step 3 — Collect results

Once the run is complete, run:

```bash
vendor-eval collect eval_results -o eval_csvs/
```

This will produce:

```
eval_csvs/
  anthropic_claude-opus-4-6.csv
  openai_gpt-5.3-codex.csv
  xai_grok-4.20-beta.csv
  summary.txt
  eval_results.zip            <- this is what you submit
```

The terminal will also print a summary like:

```
Model : xai/grok-4.20-beta
  Instances : 30
  K (rollouts / instance) : 4
  pass@4    : 46.7%  (14/30)
  passAll@4 : 33.3%  (10/30)
...
```

**Metrics explained:**

| Metric | Meaning |
|--------|---------|
| `pass@K` | % of tasks where at least 1 of K attempts passed |
| `passAll@K` | % of tasks where all K attempts passed |
| `passAll@K (all models)` | % of tasks where every model has at least one passing attempt |

**CSV columns:**

| Column | Description |
|--------|-------------|
| `instance_id` | Task identifier |
| `rollout_id` | Unique ID for this specific attempt |
| `model` | Model string (e.g. `xai/grok-4.20-beta`) |
| `reward` | `1.0` = pass, `0.0` = fail, blank = run error |
| `error` / `error_message` / `traceback` | Error details if the run crashed |
| `n_input_tokens` / `n_output_tokens` / `cost_usd` | Token usage and estimated cost |
| `n_steps` | Number of agent steps taken |
| `duration_sec` | Wall-clock time for the attempt |
| `trace` | Full agent trajectory as JSON (tool calls, observations, etc.) |

---

## Step 4 — Submit

Send the zip file `eval_csvs/eval_results.zip`, along with the zip of samples you wish to submit, to your xAI evaluation contact.

**Important:**
- Do **not** modify any CSV or the summary before submitting
- All three models must be present in the zip
- The `trace` column is used to verify result integrity — do not strip it

If you encounter any issues during setup or execution, contact your xAI evaluation contact before submitting incomplete results.

---

## What is Harbor?

[Harbor](https://github.com/harbor-framework/harbor) is an open evaluation framework built for reproducible LLM agent evals. For each task it:

- Builds an isolated Docker environment from the task's `Dockerfile`
- Installs the specified agent (`opencode`) and runs it against the task
- Runs a verifier to score the output (pass / fail)
- Records a full **ATIF trajectory** — every tool call, observation, and token count

Full documentation: https://harborframework.com/docs
