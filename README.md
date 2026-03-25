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
| Grok 4.20-beta | `xai/grok-4.20-beta` |

Note: other preferred options for grok are also `grok-4`. If you run into any issues with either of them, you can use `grok-code-fast-1` as well.

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

The simplest setup is to use a single [OpenRouter](https://openrouter.ai/) key, which lets Harbor route calls to all three models:

```bash
export OPENROUTER_API_KEY="sk-or-..."
```

If you prefer not to go through OpenRouter, you can call each provider directly by setting their individual API keys instead:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
export XAI_API_KEY="xai-..."
```

Ensure the keys for whichever approach you choose are set — the run will fail for any model whose key is missing.

---

## Step 1 — Make sure you have the sample task dataset you wish to submit

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
  -m openrouter/x-ai/grok-4.20-beta \
  -m openrouter/openai/gpt-5.3-codex \
  -m openrouter/anthropic/claude-opus-4.6 \
  -a terminus-2 \
  -k 8 \
  --job-name vendor-eval \
  --jobs-dir eval_results
```

(You can substitute the grok model with `grok-4` or if there's any issues you can use `grok-code-fast-1` although the first two are recommended)
(Also, you can substitute terminus-2 with other agents as well, just make sure that they support trajectories output in ATIF format)

If you are calling providers directly (without OpenRouter), use the provider-native model identifiers instead:

```bash
harbor run \
  -p /path/to/coding-eval-tasks \
  -m anthropic/claude-opus-4-6 \
  -m openai/gpt-5.3-codex \
  -m xai/grok-4 \
  -a terminus-2 \
  -k 8 \
  --job-name vendor-eval \
  --jobs-dir eval_results
```

Also: please try with k as 1 on a single task and make sure you can see rewards/traces before running it for the full dataset since it'll take some time.

**What each flag does:**

| Flag | Description |
|------|-------------|
| `-p <path>` | Path to the task dataset directory |
| `-m <model>` | Model to evaluate — all three must be included |
| `-a terminus-2` | You can use `terminus-2` as the coding agent harness, but feel free to use a different one — this is flexible. eg openhands or opencode |
| `-k 8` | Number of independent attempts per task — 8 is highly recommended, otherwise 4 if not possible |
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
  xai_grok-code-fast-1.csv
  summary.txt
  eval_results.zip            <- this is what you submit
```

The terminal will also print a summary like:

```
Model : xai/grok-code-fast-1
  Instances : 30
  K (rollouts / instance) : 4
  pass@4            : 46.7%  (14/30)
  passAll@4         : 33.3%  (10/30)
  avg_reward          : 0.5820
  avg_best_reward@4 : 0.7130
...
```

**Metrics explained:**

| Metric | Meaning |
|--------|---------|
| `pass@K` | % of tasks where at least 1 of K attempts passed (reward = 1.0) |
| `passAll@K` | % of tasks where all K attempts passed (reward = 1.0) |
| `avg_reward` | Mean reward across all valid rollouts |
| `avg_best_reward@K` | Mean of the per-instance best reward across K rollouts |
| `passAll@K (all models)` | % of tasks where every model has at least one passing attempt |

> **Note:** `pass@K` and `passAll@K` use binary pass/fail by default (reward = 1.0). For tasks with continuous rewards (0–1), `avg_reward` and `avg_best_reward@K` are the better indicators of model quality. You can also override the pass/fail cutoff with `--pass-threshold` (e.g. `--pass-threshold 0.5`).

**CSV columns:**

| Column | Description |
|--------|-------------|
| `instance_id` | Task identifier |
| `rollout_id` | Unique ID for this specific attempt |
| `model` | Model string (e.g. `xai/grok-code-fast-1`) |
| `reward` | Float between 0 and 1 (1.0 = full pass, 0.0 = fail, fractional = partial credit, blank = run error) |
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
- Installs the specified agent (`terminus-2`) and runs it against the task
- Runs a verifier to score the output (pass / fail)
- Records a full **ATIF trajectory** — every tool call, observation, and token count

Full documentation: https://harborframework.com/docs
