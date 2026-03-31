from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.env_loader import load_local_env
from app.core.models import ParsedInput, PipelineError, PipelineOptions
from app.services.input_parser import InputParser
from app.services.pipeline import GenerationPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ParamCAD generator")
    parser.add_argument("--input", type=Path, help="Path to JSON input file")
    parser.add_argument("--excel", type=Path, help="Path to Excel input file")
    parser.add_argument("--sheet", type=str, default=None, help="Excel sheet name")
    parser.add_argument("--dry-run", action="store_true", help="Run without real SolidWorks")
    parser.add_argument("--generate-drawing", action="store_true", help="Also generate drawing output")
    parser.add_argument("--payload", type=str, default=None, help="Inline JSON payload")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Override output root directory (default: <project>/output)",
    )
    return parser


def parse_input(args: argparse.Namespace) -> tuple[str, ParsedInput]:
    parser = InputParser()

    if args.payload:
        payload = json.loads(args.payload)
        return "payload", parser.parse_payload(payload, source="json-inline")

    if args.input:
        return "json", parser.parse_json_file(args.input)

    if args.excel:
        return "excel", parser.parse_excel_file(args.excel, sheet_name=args.sheet)

    raise ValueError("One input source is required: --input OR --excel OR --payload")


def main() -> int:
    args = build_parser().parse_args()
    project_root = Path(__file__).resolve().parents[1]
    load_local_env(project_root / ".env")
    output_root = args.output_dir if args.output_dir else (project_root / "output")

    options = PipelineOptions(
        project_root=project_root,
        output_root=output_root,
        static_root=project_root / "static",
        use_real_cad=not args.dry_run,
        generate_drawing=args.generate_drawing,
    )

    try:
        _, parsed = parse_input(args)
        pipeline = GenerationPipeline(options)
        result = pipeline.run(parsed)
        print("Run succeeded")
        print(f"Template: {result.template}")
        print(f"Part: {result.output_part}")
        if result.output_drawing:
            print(f"Drawing: {result.output_drawing}")
        print(f"Macro: {result.macro_path}")
        print(f"Log: {result.output_log}")
        if result.cad_message:
            print(f"CAD: {result.cad_message}")
        if result.warnings:
            print("Warnings:")
            for warning in result.warnings:
                print(f"  - {warning}")
        return 0
    except PipelineError as exc:
        print("Run failed")
        print(str(exc))
        for detail in exc.details:
            print(f"  - {detail}")
        return 2
    except Exception as exc:  # pragma: no cover
        print(f"Unexpected error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
