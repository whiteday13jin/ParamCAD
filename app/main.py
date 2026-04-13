from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.env_loader import load_local_env
from app.core.models import ParsedInput, PipelineError, PipelineOptions
from app.services.input_parser import InputParser
from app.services.pipeline import GenerationPipeline


def build_parser() -> argparse.ArgumentParser:
    # CLI 入口只负责描述“用户能怎么启动这条流水线”，
    # 不负责真正的业务处理。这样 CLI、API 才能共用后面的核心逻辑。
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
        # 内联 payload 最接近 API 的调用方式，所以先复用 parse_payload，
        # 让 CLI 和 Web 最终都收口到同一种内部数据结构。
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

    # PipelineOptions 是“运行环境配置”，例如静态资源目录、输出目录、是否真实 CAD。
    # 它和用户输入的业务参数是两类数据，分开后主流程更容易保持清晰。
    options = PipelineOptions(
        project_root=project_root,
        output_root=output_root,
        static_root=project_root / "static",
        use_real_cad=not args.dry_run,
        generate_drawing=args.generate_drawing,
    )

    try:
        _, parsed = parse_input(args)
        # 真正的业务装配从这里开始。入口层只把输入整理好，然后把后续职责交给 pipeline。
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
