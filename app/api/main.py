from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from app.core.models import PipelineError, PipelineOptions
from app.core.template_manager import TemplateManager
from app.services.input_parser import InputParser
from app.services.pipeline import GenerationPipeline

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_ROOT = PROJECT_ROOT / "static"
WEB_INDEX = PROJECT_ROOT / "web" / "index.html"


def _build_pipeline(
    use_real_cad: bool,
    generate_drawing: bool,
    output_dir: str | None = None,
) -> GenerationPipeline:
    project_root = PROJECT_ROOT
    output_root = Path(output_dir) if output_dir else (project_root / "output")
    options = PipelineOptions(
        project_root=project_root,
        output_root=output_root,
        static_root=STATIC_ROOT,
        use_real_cad=use_real_cad,
        generate_drawing=generate_drawing,
    )
    return GenerationPipeline(options)


app = FastAPI(title="ParamCAD", version="0.1.0")


@app.get("/", include_in_schema=False)
def web_shell() -> HTMLResponse:
    if not WEB_INDEX.exists():
        raise HTTPException(status_code=404, detail="Web page not found")
    return HTMLResponse(
        WEB_INDEX.read_text(encoding="utf-8-sig"),
        media_type="text/html; charset=utf-8",
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/templates")
def templates() -> dict[str, Any]:
    manager = TemplateManager(STATIC_ROOT / "template_registry.json")
    data = {}
    for name, spec in manager.load().items():
        data[name] = {
            "display_name": spec.display_name,
            "required": spec.required,
            "defaults": spec.defaults,
            "bounds": spec.bounds,
        }
    return {"templates": data}


@app.post("/generate")
def generate(payload: dict[str, Any]) -> dict[str, Any]:
    use_real_cad = bool(payload.get("use_real_cad", False))
    generate_drawing = bool(payload.get("generate_drawing", False))
    output_dir = payload.get("output_dir")
    output_dir = str(output_dir) if output_dir is not None else None

    cleaned_payload = dict(payload)
    cleaned_payload.pop("use_real_cad", None)
    cleaned_payload.pop("generate_drawing", None)
    cleaned_payload.pop("output_dir", None)

    parser = InputParser()
    parsed = parser.parse_payload(cleaned_payload, source="web-api")

    pipeline = _build_pipeline(
        use_real_cad=use_real_cad,
        generate_drawing=generate_drawing,
        output_dir=output_dir,
    )

    try:
        result = pipeline.run(parsed)
        return {
            "run_id": result.run_id,
            "template": result.template,
            "output_part": str(result.output_part),
            "output_drawing": str(result.output_drawing) if result.output_drawing else None,
            "output_log": str(result.output_log),
            "macro_path": str(result.macro_path),
            "version": result.version,
            "warnings": result.warnings,
            "generated_at": result.generated_at.isoformat(),
        }
    except PipelineError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "message": str(exc),
                "details": exc.details,
            },
        ) from exc
