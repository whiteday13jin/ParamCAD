from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

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
        self.template_manager = TemplateManager(registry_path)
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

        validation = self.validator.validate(template, parsed_input.parameters)
        if validation.errors:
            raise PipelineError("Validation failed", validation.errors)

        try:
            macro = self.macro_generator.generate(template, validation.normalized_parameters)
        except Exception as exc:
            raise PipelineError("Macro generation failed", [str(exc)]) from exc

        output_paths = self.output_manager.allocate_paths(template, validation.normalized_parameters)

        model_template_path = self.options.static_root / "model_templates" / template.model_template
        drawing_path = output_paths.drawing_path if self.options.generate_drawing else None

        try:
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

        log_payload = {
            "run_id": run_id,
            "template": template.name,
            "input_source": parsed_input.source,
            "raw_input": parsed_input.raw_input,
            "final_parameters": validation.normalized_parameters,
            "defaults_applied": validation.defaults_applied,
            "warnings": validation.warnings,
            "macro_template": str(macro.macro_source_path),
            "macro_generated": str(macro.macro_path),
            "part_output": str(output_paths.part_path),
            "drawing_output": str(drawing_path) if drawing_path else None,
            "version": output_paths.version,
            "cad_message": execution.message,
        }
        self.output_manager.write_log(output_paths.log_path, log_payload)

        return PipelineResult(
            run_id=run_id,
            template=template.name,
            input_source=parsed_input.source,
            output_part=output_paths.part_path,
            output_drawing=drawing_path,
            output_log=output_paths.log_path,
            macro_path=macro.macro_path,
            version=output_paths.version,
            warnings=validation.warnings,
            generated_at=datetime.utcnow(),
        )
