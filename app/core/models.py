from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class TemplateDefinition(BaseModel):
    name: str
    display_name: str
    macro_template: str
    model_template: str
    drawing_template: str | None = None
    required: list[str] = Field(default_factory=list)
    defaults: dict[str, Any] = Field(default_factory=dict)
    bounds: dict[str, dict[str, float]] = Field(default_factory=dict)
    summary_keys: list[str] = Field(default_factory=list)


class ValidationResult(BaseModel):
    template: str
    normalized_parameters: dict[str, Any] = Field(default_factory=dict)
    defaults_applied: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class ParsedInput(BaseModel):
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
    success: bool
    message: str
    part_path: Path | None = None
    drawing_path: Path | None = None


class PipelineResult(BaseModel):
    run_id: str
    template: str
    input_source: str
    output_part: Path
    output_drawing: Path | None
    output_log: Path
    macro_path: Path
    version: int
    warnings: list[str] = Field(default_factory=list)
    generated_at: datetime


class PipelineOptions(BaseModel):
    project_root: Path
    output_root: Path
    static_root: Path
    use_real_cad: bool = False
    generate_drawing: bool = False


class PipelineError(Exception):
    def __init__(self, message: str, details: list[str] | None = None):
        super().__init__(message)
        self.details = details or []
