"""Parse Harbor job directories and emit one CSV per model."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Row dataclass (plain dict so it serialises trivially)
# ---------------------------------------------------------------------------

FIELDS = [
    "instance_id",
    "rollout_id",
    "job_name",
    "source",
    "agent",
    "model",
    "reward",
    "error",
    "error_message",
    "traceback",
    "n_input_tokens",
    "n_output_tokens",
    "n_cache_tokens",
    "cost_usd",
    "n_steps",
    "total_prompt_tokens",
    "total_completion_tokens",
    "total_cached_tokens",
    "total_cost_usd",
    "duration_sec",
    "started_at",
    "finished_at",
    "task_checksum",
    "session_id",
    "trace",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _iso_to_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _duration(started: str | None, finished: str | None) -> float | None:
    s, f = _iso_to_dt(started), _iso_to_dt(finished)
    if s and f:
        return round((f - s).total_seconds(), 3)
    return None


def _model_slug(model_name: str) -> str:
    """Turn 'xai/grok-code-fast-1' → 'xai_grok-code-fast-1' for filenames."""
    return model_name.replace("/", "_").replace(":", "_")


def _load_trace(trial_dir: Path) -> str | None:
    """Return the ATIF trajectory steps as a compact JSON string, or None."""
    traj_path = trial_dir / "agent" / "trajectory.json"
    if not traj_path.exists():
        return None
    data = _read_json(traj_path)
    if data is None:
        return None
    # Compact-encode just the steps to keep the cell readable
    steps = data.get("steps", [])
    try:
        return json.dumps(steps, separators=(",", ":"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Trial parser
# ---------------------------------------------------------------------------


def _parse_trial(trial_dir: Path, job_name: str) -> dict[str, Any] | None:
    """Return a flat row dict for one trial directory, or None if not parseable."""
    result_path = trial_dir / "result.json"
    if not result_path.exists():
        return None

    result = _read_json(result_path)
    if result is None:
        return None

    # ---- identity ---------------------------------------------------------
    task_name = result.get("task_name", trial_dir.name.rsplit("__", 1)[0])
    trial_name = result.get("trial_name", trial_dir.name)
    source = result.get("source", "")
    checksum = result.get("task_checksum", "")

    # ---- agent / model ----------------------------------------------------
    agent_info = result.get("agent_info") or {}
    model_info = agent_info.get("model_info") or {}
    agent_name = agent_info.get("name", "")

    # Prefer agent_info; fall back to config.agent
    config = result.get("config") or {}
    cfg_agent = config.get("agent") or {}
    model_name = cfg_agent.get("model_name", "")
    if model_info.get("provider") and model_info.get("name"):
        model_name = f"{model_info['provider']}/{model_info['name']}"

    # ---- reward -----------------------------------------------------------
    verifier = result.get("verifier_result") or {}
    rewards = verifier.get("rewards") or {}
    reward = rewards.get("reward")  # may be None if error

    # ---- tokens / cost from agent_result ----------------------------------
    agent_result = result.get("agent_result") or {}
    n_input = agent_result.get("n_input_tokens")
    n_output = agent_result.get("n_output_tokens")
    n_cache = agent_result.get("n_cache_tokens")
    cost = agent_result.get("cost_usd")

    # ---- error ------------------------------------------------------------
    exc = result.get("exception_info") or {}
    error = exc.get("exception_type")
    error_msg = exc.get("exception_message")
    traceback = exc.get("exception_traceback")

    # ---- timing -----------------------------------------------------------
    started_at = result.get("started_at")
    finished_at = result.get("finished_at")
    duration = _duration(started_at, finished_at)

    # ---- trajectory -------------------------------------------------------
    traj_path = trial_dir / "agent" / "trajectory.json"
    traj_data = _read_json(traj_path) if traj_path.exists() else None
    final_met = (traj_data or {}).get("final_metrics") or {}
    session_id = (traj_data or {}).get("session_id")
    n_steps = final_met.get("total_steps")
    total_prompt = final_met.get("total_prompt_tokens")
    total_completion = final_met.get("total_completion_tokens")
    total_cached = final_met.get("total_cached_tokens")
    total_cost = final_met.get("total_cost_usd")
    trace = _load_trace(trial_dir)

    return {
        "instance_id": task_name,
        "rollout_id": trial_name,
        "job_name": job_name,
        "source": source,
        "agent": agent_name,
        "model": model_name,
        "reward": reward,
        "error": error,
        "error_message": error_msg,
        "traceback": traceback,
        "n_input_tokens": n_input,
        "n_output_tokens": n_output,
        "n_cache_tokens": n_cache,
        "cost_usd": cost,
        "n_steps": n_steps,
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_completion,
        "total_cached_tokens": total_cached,
        "total_cost_usd": total_cost,
        "duration_sec": duration,
        "started_at": started_at,
        "finished_at": finished_at,
        "task_checksum": checksum,
        "session_id": session_id,
        "trace": trace,
    }


# ---------------------------------------------------------------------------
# Job-directory walker
# ---------------------------------------------------------------------------


def _is_trial_dir(path: Path) -> bool:
    """Heuristic: a trial dir has result.json and at least one of agent/ verifier/."""
    return (
        path.is_dir()
        and (path / "result.json").exists()
        and ((path / "agent").exists() or (path / "verifier").exists())
    )


def collect(jobs_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """
    Walk *jobs_dir* and parse every trial, returning a dict
    mapping  model_slug  →  list-of-row-dicts.

    Supports two layouts:
      1. jobs_dir/<job_name>/  where each job_name dir has config.json + trial dirs
      2. jobs_dir/             is itself the job dir (trial dirs are direct children)
    """
    rows_by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)

    # Collect all subdirs that look like job directories (have a config.json).
    job_dirs: list[Path] = [
        child
        for child in sorted(jobs_dir.iterdir())
        if child.is_dir() and (child / "config.json").exists()
    ]

    # If none found, treat jobs_dir itself as the job dir.
    if not job_dirs:
        job_dirs = [jobs_dir]

    for job_dir in job_dirs:
        job_name = job_dir.name
        for entry in sorted(job_dir.iterdir()):
            if not _is_trial_dir(entry):
                continue
            row = _parse_trial(entry, job_name)
            if row is None:
                continue
            model = row.get("model") or "unknown"
            rows_by_model[_model_slug(model)].append(row)

    return dict(rows_by_model)


# ---------------------------------------------------------------------------
# CSV writer
# ---------------------------------------------------------------------------


def write_csvs(rows_by_model: dict[str, list[dict]], output_dir: Path) -> list[Path]:
    """Write one CSV per model slug into *output_dir*. Returns list of written paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for slug, rows in sorted(rows_by_model.items()):
        out_path = output_dir / f"{slug}.csv"
        with out_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        written.append(out_path)

    return written


# ---------------------------------------------------------------------------
# Summary (pass@K / passAll@K)
# ---------------------------------------------------------------------------


def compute_summary(
    rows_by_model: dict[str, list[dict]],
    pass_threshold: float = 1.0,
) -> str:
    """
    Compute pass@K, passAll@K, and continuous reward metrics for each model,
    plus a cross-model passAll@K.

    Parameters
    ----------
    pass_threshold : float
        Minimum reward value to count a rollout as "passing" (default 1.0).
        Use a value < 1.0 for tasks with continuous / partial-credit rewards.

    Definitions
    -----------
    pass@K            : fraction of instances where AT LEAST ONE of K rollouts
                        has reward >= pass_threshold
    passAll@K         : fraction of instances where ALL K rollouts have
                        reward >= pass_threshold
    avg_reward        : mean reward across all valid rollouts
    avg_best_reward@K : mean of the per-instance best reward across K rollouts
    passAll@K (all models) : fraction of instances where every model's
                             pass@K = 1 (i.e. at least one rollout passes for
                             every model)
    """
    lines: list[str] = ["=" * 60, "vendor-eval summary", "=" * 60, ""]

    if pass_threshold != 1.0:
        lines.append(f"  pass threshold : {pass_threshold}")
        lines.append("")

    # Per-model stats
    model_pass: dict[str, set[str]] = {}  # slug → set of instance_ids that pass@K
    all_instance_ids: set[str] = set()

    per_model_lines: list[str] = []

    for slug, rows in sorted(rows_by_model.items()):
        # Group rollouts by instance_id
        by_instance: dict[str, list[float | None]] = {}
        for row in rows:
            iid = row["instance_id"]
            reward = row.get("reward")
            by_instance.setdefault(iid, []).append(float(reward) if reward is not None else None)

        all_instance_ids.update(by_instance.keys())
        n_instances = len(by_instance)

        # Infer K (max rollouts seen for any instance)
        k = max((len(v) for v in by_instance.values()), default=1)

        pass_k_count = 0
        pass_all_k_count = 0
        passing_instances: set[str] = set()
        all_valid_rewards: list[float] = []
        best_per_instance: list[float] = []

        for iid, rewards in by_instance.items():
            valid = [r for r in rewards if r is not None]
            if not valid:
                continue
            all_valid_rewards.extend(valid)
            best_per_instance.append(max(valid))
            if max(valid) >= pass_threshold:
                pass_k_count += 1
                passing_instances.add(iid)
            if min(valid) >= pass_threshold:
                pass_all_k_count += 1

        model_pass[slug] = passing_instances

        pass_k_pct = 100 * pass_k_count / n_instances if n_instances else 0.0
        pass_all_k_pct = 100 * pass_all_k_count / n_instances if n_instances else 0.0
        avg_reward = sum(all_valid_rewards) / len(all_valid_rewards) if all_valid_rewards else 0.0
        avg_best = sum(best_per_instance) / len(best_per_instance) if best_per_instance else 0.0

        # Use original model name if available
        model_name = rows[0].get("model") or slug

        per_model_lines += [
            f"Model : {model_name}",
            f"  Instances : {n_instances}",
            f"  K (rollouts / instance) : {k}",
            f"  pass@{k}            : {pass_k_pct:.1f}%  ({pass_k_count}/{n_instances})",
            f"  passAll@{k}         : {pass_all_k_pct:.1f}%  ({pass_all_k_count}/{n_instances})",
            f"  avg_reward          : {avg_reward:.4f}",
            f"  avg_best_reward@{k} : {avg_best:.4f}",
            "",
        ]

    lines += per_model_lines

    # Cross-model passAll@K: instances where every model has at least one pass
    if len(model_pass) > 1 and all_instance_ids:
        cross_pass = all_instance_ids.copy()
        for passing in model_pass.values():
            cross_pass &= passing
        n_total = len(all_instance_ids)
        n_cross = len(cross_pass)
        pct = 100 * n_cross / n_total if n_total else 0.0
        lines += [
            "-" * 60,
            f"passAll@K (all {len(model_pass)} models) : {pct:.1f}%  ({n_cross}/{n_total})",
            "(instances where every model has at least one passing rollout)",
            "",
        ]

    lines.append("=" * 60)
    return "\n".join(lines) + "\n"


def compute_summary_dict(
    rows_by_model: dict[str, list[dict]],
    pass_threshold: float = 1.0,
) -> dict:
    """
    Return the same stats as compute_summary but as a structured dict suitable
    for JSON serialisation.

    Parameters
    ----------
    pass_threshold : float
        Minimum reward value to count a rollout as "passing" (default 1.0).

    Schema
    ------
    {
        "pass_threshold": float,
        "models": {
            "<model_name>": {
                "instances": int,
                "k": int,
                "pass_at_k": float,              # fraction [0, 1]
                "pass_at_k_count": int,
                "pass_all_at_k": float,
                "pass_all_at_k_count": int,
                "avg_reward": float,              # mean of all valid rollout rewards
                "avg_best_reward_at_k": float,    # mean of per-instance best reward
            },
            ...
        },
        "cross_model": {                          # only present when > 1 model
            "n_models": int,
            "total_instances": int,
            "pass_all_at_k": float,
            "pass_all_at_k_count": int,
        }
    }
    """
    models_out: dict = {}
    model_pass: dict[str, set[str]] = {}
    all_instance_ids: set[str] = set()

    for slug, rows in sorted(rows_by_model.items()):
        by_instance: dict[str, list[float | None]] = {}
        for row in rows:
            iid = row["instance_id"]
            reward = row.get("reward")
            by_instance.setdefault(iid, []).append(float(reward) if reward is not None else None)

        all_instance_ids.update(by_instance.keys())
        n_instances = len(by_instance)
        k = max((len(v) for v in by_instance.values()), default=1)

        pass_k_count = 0
        pass_all_k_count = 0
        passing_instances: set[str] = set()
        all_valid_rewards: list[float] = []
        best_per_instance: list[float] = []

        for iid, rewards in by_instance.items():
            valid = [r for r in rewards if r is not None]
            if not valid:
                continue
            all_valid_rewards.extend(valid)
            best_per_instance.append(max(valid))
            if max(valid) >= pass_threshold:
                pass_k_count += 1
                passing_instances.add(iid)
            if min(valid) >= pass_threshold:
                pass_all_k_count += 1

        model_pass[slug] = passing_instances
        model_name = rows[0].get("model") or slug

        avg_reward = sum(all_valid_rewards) / len(all_valid_rewards) if all_valid_rewards else 0.0
        avg_best = sum(best_per_instance) / len(best_per_instance) if best_per_instance else 0.0

        models_out[model_name] = {
            "instances": n_instances,
            "k": k,
            "pass_at_k": round(pass_k_count / n_instances, 6) if n_instances else 0.0,
            "pass_at_k_count": pass_k_count,
            "pass_all_at_k": round(pass_all_k_count / n_instances, 6) if n_instances else 0.0,
            "pass_all_at_k_count": pass_all_k_count,
            "avg_reward": round(avg_reward, 6),
            "avg_best_reward_at_k": round(avg_best, 6),
        }

    result: dict = {"pass_threshold": pass_threshold, "models": models_out}

    if len(model_pass) > 1 and all_instance_ids:
        cross_pass = all_instance_ids.copy()
        for passing in model_pass.values():
            cross_pass &= passing
        n_total = len(all_instance_ids)
        n_cross = len(cross_pass)
        result["cross_model"] = {
            "n_models": len(model_pass),
            "total_instances": n_total,
            "pass_all_at_k": round(n_cross / n_total, 6) if n_total else 0.0,
            "pass_all_at_k_count": n_cross,
        }

    return result


def write_summary(
    rows_by_model: dict[str, list[dict]],
    output_dir: Path,
    pass_threshold: float = 1.0,
) -> Path:
    """Write summary.txt into *output_dir* and return its path."""
    summary = compute_summary(rows_by_model, pass_threshold=pass_threshold)
    out_path = output_dir / "summary.txt"
    out_path.write_text(summary, encoding="utf-8")
    return out_path


def write_summary_json(
    rows_by_model: dict[str, list[dict]],
    output_dir: Path,
    pass_threshold: float = 1.0,
) -> Path:
    """Write summary.json into *output_dir* and return its path."""
    data = compute_summary_dict(rows_by_model, pass_threshold=pass_threshold)
    out_path = output_dir / "summary.json"
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return out_path
