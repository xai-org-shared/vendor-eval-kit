"""CLI entry point for vendor-eval."""

from __future__ import annotations

import csv
import sys
import zipfile
from pathlib import Path

csv.field_size_limit(sys.maxsize)

import click

from vendor_eval.collect import collect, compute_summary, write_csvs, write_summary, write_summary_json


@click.group()
def cli() -> None:
    """vendor-eval — collect and export Harbor coding eval results."""


@cli.command("collect")
@click.argument(
    "jobs_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "-o",
    "--output-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Directory to write output into (default: <jobs_dir>/vendor-eval-output).",
)
@click.option(
    "-t",
    "--pass-threshold",
    type=float,
    default=1.0,
    show_default=True,
    help=(
        "Minimum reward to count a rollout as passing. "
        "Use 1.0 (default) for binary pass/fail tasks. "
        "Set lower (e.g. 0.5) for tasks with continuous / partial-credit rewards."
    ),
)
def collect_cmd(jobs_dir: Path, output_dir: Path | None, pass_threshold: float) -> None:
    """Collect Harbor trial results under JOBS_DIR and write one CSV per model + summary."""
    if not 0.0 <= pass_threshold <= 1.0:
        click.echo("Error: --pass-threshold must be between 0.0 and 1.0.", err=True)
        raise SystemExit(1)

    if output_dir is None:
        output_dir = jobs_dir / "vendor-eval-output"

    click.echo(f"Scanning {jobs_dir} ...")
    rows_by_model = collect(jobs_dir)

    if not rows_by_model:
        click.echo("No trial results found.", err=True)
        raise SystemExit(1)

    written = write_csvs(rows_by_model, output_dir)
    summary_path = write_summary(rows_by_model, output_dir, pass_threshold=pass_threshold)
    summary_json_path = write_summary_json(rows_by_model, output_dir, pass_threshold=pass_threshold)

    click.echo(f"\nWrote {len(written)} CSV(s) to {output_dir}/")
    for path in written:
        with path.open(newline="", encoding="utf-8") as fh:
            n_rows = sum(1 for _ in csv.reader(fh)) - 1  # subtract header
        click.echo(f"  {path.name}  ({n_rows} rows)")
    click.echo(f"  {summary_path.name}")
    click.echo(f"  {summary_json_path.name}")

    # Print summary to terminal
    click.echo("")
    click.echo(compute_summary(rows_by_model, pass_threshold=pass_threshold))

    # Create zip named after the jobs_dir containing CSVs + summary
    zip_name = jobs_dir.resolve().name + ".zip"
    zip_path = output_dir / zip_name
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in written:
            zf.write(path, arcname=path.name)
        zf.write(summary_path, arcname=summary_path.name)
        zf.write(summary_json_path, arcname=summary_json_path.name)
    click.echo(f"  → {zip_path}")
