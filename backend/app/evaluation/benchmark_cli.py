import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Sequence

from app.core.config import settings
from app.evaluation.benchmark import (
    BenchmarkRunner,
    create_historical_cost_report,
    compare_reports,
    write_comparison,
    write_report,
)
from app.evaluation.dataset import DEFAULT_DATASET_PATH


def _read_report(path: str | Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to read benchmark report: {path}") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run or compare TestNova test-case generation benchmarks."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    run_parser = commands.add_parser("run", help="Run selected provider/model")
    run_parser.add_argument("--provider", choices=("gemini", "groq"), required=True)
    run_parser.add_argument("--model", required=True)
    run_parser.add_argument("--dataset", default=str(DEFAULT_DATASET_PATH))
    run_parser.add_argument("--dataset-version")
    run_parser.add_argument("--example-id", action="append", dest="example_ids")
    run_parser.add_argument("--temperature", type=float, default=0.0)
    run_parser.add_argument("--output-dir", required=True)
    run_parser.add_argument(
        "--live",
        action="store_true",
        help="Explicitly allow real provider calls (uses configured credentials).",
    )
    run_parser.add_argument("--run-id")

    compare_parser = commands.add_parser(
        "compare",
        help="Create a comparison report from completed benchmark JSON reports",
    )
    compare_parser.add_argument("reports", nargs="+")
    compare_parser.add_argument("--output-dir", required=True)

    cost_parser = commands.add_parser(
        "cost",
        help="Create a separate cost estimate from a historical benchmark report",
    )
    cost_parser.add_argument("report")
    cost_parser.add_argument("--output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "cost":
        source_path = Path(args.report)
        output_path = Path(args.output)
        try:
            if source_path.resolve() == output_path.resolve():
                raise ValueError("Cost output must not overwrite the source report")
            if output_path.exists():
                raise ValueError(
                    f"Cost output already exists and will not be overwritten: "
                    f"{output_path}"
                )
            source_bytes = source_path.read_bytes()
            report = json.loads(source_bytes.decode("utf-8"))
            cost_report = create_historical_cost_report(
                report,
                pricing=settings.LLM_PRICING,
                currency=settings.LLM_PRICING_CURRENCY,
                pricing_version=settings.LLM_PRICING_VERSION,
                source_sha256=hashlib.sha256(source_bytes).hexdigest(),
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(cost_report, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(f"Cost report: {output_path}")
        return 0

    if args.command == "run":
        if not args.live:
            parser.error(
                "run is disabled by default; add --live to explicitly allow "
                "external provider calls."
            )
        try:
            runner = BenchmarkRunner.from_path(
                args.dataset,
                expected_version=args.dataset_version,
            )
            report = runner.run(
                provider_name=args.provider,
                model_name=args.model,
                run_id=args.run_id,
                selected_example_ids=(
                    set(args.example_ids) if args.example_ids is not None else None
                ),
                temperature=args.temperature,
                execution_mode="live",
            )
            json_path, markdown_path = write_report(report, args.output_dir)
        except (ValueError, RuntimeError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(f"Benchmark JSON: {json_path}")
        print(f"Benchmark Markdown: {markdown_path}")
        return 0

    try:
        reports = [_read_report(path) for path in args.reports]
        comparison = compare_reports(reports)
        json_path, markdown_path = write_comparison(
            comparison,
            args.output_dir,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"Comparison JSON: {json_path}")
    print(f"Comparison Markdown: {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
