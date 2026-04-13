from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from app.core.capabilities import TemplateCapabilityInspector
from app.core.env_loader import load_local_env
from app.core.models import LLMPlanRequest, PipelineError, PipelineOptions
from app.core.template_manager import TemplateManager
from app.services.input_parser import InputParser
from app.services.llm_client import LLMSettings, OpenAICompatibleLLMClient
from app.services.llm_planner import ParamCADLLMPlanner
from app.services.pipeline import GenerationPipeline
from app.core.validation import Validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_ROOT = PROJECT_ROOT / "static"
WEB_INDEX = PROJECT_ROOT / "web" / "index.html"

load_local_env(PROJECT_ROOT / ".env")


def _build_pipeline(
    use_real_cad: bool,
    generate_drawing: bool,
    output_dir: str | None = None,
) -> GenerationPipeline:
    project_root = PROJECT_ROOT
    output_root = Path(output_dir) if output_dir else (project_root / "output")
    # API 和 CLI 都通过 PipelineOptions 去描述运行上下文，
    # 这样“入口不同、核心逻辑相同”的结构会非常明确。
    options = PipelineOptions(
        project_root=project_root,
        output_root=output_root,
        static_root=STATIC_ROOT,
        use_real_cad=use_real_cad,
        generate_drawing=generate_drawing,
    )
    return GenerationPipeline(options)


def _build_llm_planner() -> ParamCADLLMPlanner:
    # LLM planner 自己不直接持有全局单例，而是按需组装依赖。
    # 这样每次请求都能明确看到：模板定义、能力检查、规则校验、LLM 客户端是如何协作的。
    manager = TemplateManager(STATIC_ROOT / "template_registry.json")
    capability_inspector = TemplateCapabilityInspector(STATIC_ROOT / "template_bindings.json")
    validator = Validator()
    client = OpenAICompatibleLLMClient(LLMSettings.from_env())
    return ParamCADLLMPlanner(
        template_manager=manager,
        capability_inspector=capability_inspector,
        validator=validator,
        llm_client=client,
    )


app = FastAPI(title="ParamCAD", version="0.9.0")


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


@app.get("/pick-output-dir")
def pick_output_dir() -> dict[str, str]:
    try:
        from tkinter import Tk, filedialog

        root = Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(title="选择 ParamCAD 输出目录")
        root.destroy()
        return {"path": selected or ""}
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "打开目录选择器失败",
                "details": [str(exc)],
            },
        ) from exc


@app.post("/open-path")
def open_path(path: str = Query(..., description="文件或目录路径")) -> dict[str, str]:
    try:
        target = Path(path).expanduser()
        if not target.exists():
            raise HTTPException(
                status_code=404,
                detail={
                    "message": "目标路径不存在",
                    "details": [str(target)],
                },
            )

        if target.is_file():
            subprocess.Popen(["explorer.exe", "/select,", str(target)])
            opened = str(target.parent)
        else:
            subprocess.Popen(["explorer.exe", str(target)])
            opened = str(target)

        return {"opened": opened}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "打开文件目录失败",
                "details": [str(exc)],
            },
        ) from exc


@app.get("/templates")
def templates() -> dict[str, Any]:
    manager = TemplateManager(STATIC_ROOT / "template_registry.json")
    capability_inspector = TemplateCapabilityInspector(STATIC_ROOT / "template_bindings.json")
    data = {}
    for name, spec in manager.load().items():
        capability_report = capability_inspector.describe(spec)
        # partial 模板会刻意只把“当前稳定可执行”的参数暴露给前端，
        # 避免界面把用户引到暂未真正接通的字段上。
        visible_parameters = capability_report["effective_parameters"] if spec.support_level != "stable" else capability_report["declared_parameters"]
        hidden_parameters = sorted(set(capability_report["declared_parameters"]) - set(visible_parameters))
        data[name] = {
            "display_name": spec.display_name,
            "support_level": spec.support_level,
            "llm_ready": spec.llm_ready,
            "status_notes": spec.status_notes,
            "required": spec.required,
            "defaults": spec.defaults,
            "bounds": spec.bounds,
            "effective_parameters": capability_report["effective_parameters"],
            "inactive_parameters": capability_report["inactive_parameters"],
            "required_inactive_parameters": capability_report["required_inactive_parameters"],
            "visible_parameters": visible_parameters,
            "hidden_parameters": hidden_parameters,
            "notes": capability_report["notes"],
        }
    return {"templates": data}


@app.post("/generate")
def generate(payload: dict[str, Any]) -> dict[str, Any]:
    use_real_cad = bool(payload.get("use_real_cad", False))
    generate_drawing = bool(payload.get("generate_drawing", False))
    output_dir = payload.get("output_dir")
    output_dir = str(output_dir) if output_dir is not None else None

    # 这几个字段属于“运行控制参数”，不应该混进业务参数里一起校验，
    # 所以在 parse_payload 之前先从 payload 中剥离出来。
    cleaned_payload = dict(payload)
    cleaned_payload.pop("use_real_cad", None)
    cleaned_payload.pop("generate_drawing", None)
    cleaned_payload.pop("output_dir", None)

    parser = InputParser()
    # Web 入口最终也收口成 ParsedInput，后面的 pipeline 因而无需关心输入来自页面还是文件。
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
            "cad_message": result.cad_message,
            "cad_details": result.cad_details,
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


@app.post("/llm/plan")
def llm_plan(payload: LLMPlanRequest) -> dict[str, Any]:
    try:
        planner = _build_llm_planner()
        # 这条接口只做“提案”，不做真实生成。
        # 用户先看到参数 patch、默认值建议和风险提示，再决定是否采纳。
        result = planner.plan(payload.text)
        return result.model_dump()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "LLM 提案服务当前不可用",
                "details": [str(exc)],
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "LLM 提案结果解析失败",
                "details": [str(exc)],
            },
        ) from exc
