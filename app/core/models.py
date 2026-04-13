from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator


class TemplateDefinition(BaseModel):
    # 这是“模板在业务层长什么样”的统一合同。
    # registry.json 读取进来后，会先被提升成这个强类型对象，后续代码就不用到处猜字段。
    name: str
    display_name: str
    macro_template: str
    model_template: str
    drawing_template: str | None = None
    support_level: str = "partial"
    llm_ready: bool = False
    status_notes: list[str] = Field(default_factory=list)
    required: list[str] = Field(default_factory=list)
    defaults: dict[str, Any] = Field(default_factory=dict)
    bounds: dict[str, dict[str, float]] = Field(default_factory=dict)
    summary_keys: list[str] = Field(default_factory=list)


class ValidationResult(BaseModel):
    # validate 阶段不直接改外部状态，而是返回一个显式结果对象：
    # 什么被补默认值了、什么是 warning、什么是 error，都集中放在这里。
    template: str
    normalized_parameters: dict[str, Any] = Field(default_factory=dict)
    defaults_applied: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class ParsedInput(BaseModel):
    # 不同来源的输入最终都要压到这个对象里，
    # pipeline 因而可以只关心“模板 + 参数 + 原始来源”，不用关心输入来自哪里。
    template: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    raw_input: dict[str, Any] = Field(default_factory=dict)
    source: str = "json"


class GeneratedMacro(BaseModel):
    template_name: str
    macro_path: Path
    macro_source_path: Path


class OutputPaths(BaseModel):
    version: int
    part_path: Path
    drawing_path: Path | None = None
    log_path: Path


class ExecutionResult(BaseModel):
    # 执行器层返回的对象故意比 PipelineResult 更贴近底层执行语义，
    # 例如 success/message/details，便于把 CAD 真实信息往上抬。
    success: bool
    message: str
    part_path: Path | None = None
    drawing_path: Path | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class PipelineResult(BaseModel):
    # 这是对 CLI / API 最终暴露的汇总结果对象，
    # 它代表“整条流水线成功跑完后，外部最关心的是什么”。
    run_id: str
    template: str
    input_source: str
    output_part: Path
    output_drawing: Path | None
    output_log: Path
    macro_path: Path
    version: int
    warnings: list[str] = Field(default_factory=list)
    cad_message: str = ""
    cad_details: dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime


class PipelineOptions(BaseModel):
    # 运行选项和业务参数分离，是这个项目结构清晰的一个关键点。
    # 这里描述的是环境与行为开关，而不是模板业务数据。
    project_root: Path
    output_root: Path
    static_root: Path
    use_real_cad: bool = False
    generate_drawing: bool = False


class PipelineError(Exception):
    def __init__(self, message: str, details: list[str] | None = None):
        super().__init__(message)
        self.details = details or []


class LLMPlanRequest(BaseModel):
    text: str


class LLMProposedOp(BaseModel):
    op: str
    label: str = ""
    status: str = "proposal_only"
    reason: str = ""
    arguments: dict[str, Any] = Field(default_factory=dict)


class LLMPlanResponse(BaseModel):
    # LLM 返回的不是最终命令，而是一份“待确认提案”。
    # 所以这里同时保留 patch、显式提取值、推断值、默认值建议和风险提示。
    status: str
    template: str | None = None
    parameter_patch: dict[str, Any] = Field(default_factory=dict)
    explicit_parameters: dict[str, Any] = Field(default_factory=dict)
    inferred_parameters: dict[str, Any] = Field(default_factory=dict)
    suggested_defaults: dict[str, Any] = Field(default_factory=dict)
    proposed_ops: list[LLMProposedOp] = Field(default_factory=list)
    missing_or_uncertain: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
    summary: str = ""

    @field_validator("parameter_patch", mode="before")
    @classmethod
    def ensure_patch_dict(cls, value: Any) -> dict[str, Any]:
        # LLM 输出经常会有结构漂移，这里先把形状钉住，
        # 让后面的 planner 逻辑可以假设字段至少是个 dict。
        return value if isinstance(value, dict) else {}

    @field_validator("proposed_ops", mode="before")
    @classmethod
    def ensure_proposed_ops_list(cls, value: Any) -> list[dict[str, Any]] | list[LLMProposedOp]:
        # proposed_ops 代表“识别到了，但当前只保留为提议的特征请求”。
        # 先统一成 list，可以避免模型输出格式不稳定时把整个流程拖垮。
        return value if isinstance(value, list) else []
