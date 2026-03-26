from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.core.models import GeneratedMacro, TemplateDefinition


class MacroGenerator:
    def __init__(self, macro_templates_dir: Path, output_macro_dir: Path):
        self.macro_templates_dir = macro_templates_dir
        self.output_macro_dir = output_macro_dir
        self.output_macro_dir.mkdir(parents=True, exist_ok=True)

        self._env = Environment(
            loader=FileSystemLoader(str(self.macro_templates_dir)),
            autoescape=False,
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def generate(self, template: TemplateDefinition, parameters: dict[str, Any]) -> GeneratedMacro:
        macro_template_path = self.macro_templates_dir / template.macro_template
        if not macro_template_path.exists():
            raise FileNotFoundError(f"Macro template not found: {macro_template_path}")

        jinja_template = self._env.get_template(template.macro_template)
        render_context = {
            **parameters,
            "template_name": template.name,
            "generated_at": datetime.utcnow().isoformat(),
        }
        body = jinja_template.render(**render_context)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        macro_file = self.output_macro_dir / f"{template.name}_{stamp}.swp"
        macro_file.write_text(body, encoding="utf-8")

        return GeneratedMacro(
            template_name=template.name,
            macro_path=macro_file,
            macro_source_path=macro_template_path,
        )
