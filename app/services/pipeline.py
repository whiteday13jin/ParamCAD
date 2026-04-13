from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.core.capabilities import TemplateCapabilityInspector
from app.core.message_localizer import localize_messages, template_text
from app.core.models import ParsedInput, PipelineError, PipelineOptions, PipelineResult
from app.core.template_manager import TemplateManager
from app.core.validation import Validator

from .cad_executor import DryRunExecutor, SolidWorksExecutor
from .macro_generator import MacroGenerator
from .output_manager import OutputManager


class GenerationPipeline:
    def __init__(self, options: PipelineOptions):
        self.options = options
        registry_path = options.static_root / "template_registry.json"
        # pipeline 在初始化时把“模板定义、能力检查、校验、输出、宏、执行器”这些阶段装配好。
        # run() 里做的就是按顺序驱动这些组件协作。
        self.template_manager = TemplateManager(registry_path)
        self.capability_inspector = TemplateCapabilityInspector(
            binding_path=options.static_root / "template_bindings.json",
        )
        self.validator = Validator()
        self.output_manager = OutputManager(options.output_root)
        self.macro_generator = MacroGenerator(
            macro_templates_dir=options.static_root / "macro_templates",
            output_macro_dir=options.output_root / "macros",
        )
        self.executor = (
            SolidWorksExecutor(
                binding_path=options.static_root / "template_bindings.json",
            )
            if options.use_real_cad
            else DryRunExecutor()
        )

    def run(self, parsed_input: ParsedInput) -> PipelineResult:
        run_id = str(uuid4())

        try:
            template = self.template_manager.get(parsed_input.template)
        except KeyError as exc:
            raise PipelineError(str(exc)) from exc

        # 先做 capability 描述，再做 validate。
        # 这是因为“当前执行器到底接通了哪些参数”会直接影响 warning 和 LLM/前端可见能力边界。
        capability_report = self.capability_inspector.describe(template)
        validation = self.validator.validate(
            template,
            parsed_input.parameters,
            executable_parameters=set(capability_report["effective_parameters"]),
        )
        if validation.errors:
            raise PipelineError("Validation failed", localize_messages(validation.errors, template.name))

        warnings = localize_messages(validation.warnings, template.name)
        if template.support_level != "stable":
            # partial 模板即便校验通过，也额外提醒用户它还不属于“完全放心直出”的层级。
            warnings.append(
                f"{template_text(template.name)} 当前处于部分支持阶段，建议先 dry-run 或人工复核后再依赖真实 CAD 输出。"
            )

        try:
            # 宏生成先于执行发生，意味着真正调用 SolidWorks 时用的是一份已经落盘的可追踪产物。
            macro = self.macro_generator.generate(template, validation.normalized_parameters)
        except Exception as exc:
            raise PipelineError("Macro generation failed", [str(exc)]) from exc

        # 输出路径在执行前就统一分配好，这样后面的日志、零件、工程图引用的是同一套版本号。
        output_paths = self.output_manager.allocate_paths(template, validation.normalized_parameters)

        model_template_path = self.options.static_root / "model_templates" / template.model_template
        drawing_path = output_paths.drawing_path if self.options.generate_drawing else None

        try:
            # 执行器层只关心“给我模板路径、参数、宏路径、输出路径”，
            # 它不需要知道这些参数是 JSON 来的、Excel 来的还是 LLM 采纳来的。
            execution = self.executor.execute(
                template_name=template.name,
                parameters=validation.normalized_parameters,
                model_template_path=model_template_path,
                macro_path=macro.macro_path,
                output_part_path=output_paths.part_path,
                output_drawing_path=drawing_path,
            )
        except Exception as exc:
            raise PipelineError("CAD execution failed", [str(exc)]) from exc

        if not execution.success:
            raise PipelineError("CAD execution failed", [execution.message])

        # log_payload 基本上就是“这次运行的审计快照”。
        # 它把输入、默认值补全、能力报告、执行反馈统一记录下来，后续排查会非常有帮助。
        log_payload = {
            "run_id": run_id,
            "template": template.name,
            "input_source": parsed_input.source,
            "raw_input": parsed_input.raw_input,
            "final_parameters": validation.normalized_parameters,
            "defaults_applied": validation.defaults_applied,
            "warnings": warnings,
            "capability_report": capability_report,
            "template_support_level": template.support_level,
            "template_llm_ready": template.llm_ready,
            "template_status_notes": template.status_notes,
            "macro_template": str(macro.macro_source_path),
            "macro_generated": str(macro.macro_path),
            "part_output": str(output_paths.part_path),
            "drawing_output": str(drawing_path) if drawing_path else None,
            "version": output_paths.version,
            "cad_message": execution.message,
            "cad_details": execution.details,
        }
        self.output_manager.write_log(output_paths.log_path, log_payload)

        # PipelineResult 是对外汇总结果。
        # 到这里为止，前面的内部阶段细节已经被压成“外部最需要知道的成功产物”。
        return PipelineResult(
            run_id=run_id,
            template=template.name,
            input_source=parsed_input.source,
            output_part=output_paths.part_path,
            output_drawing=drawing_path,
            output_log=output_paths.log_path,
            macro_path=macro.macro_path,
            version=output_paths.version,
            warnings=warnings,
            cad_message=execution.message,
            cad_details=execution.details,
            generated_at=datetime.utcnow(),
        )
