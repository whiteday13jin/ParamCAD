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
            # 宏模板里一旦引用了不存在的变量，宁可立刻失败，
            # 也不要悄悄生成一个缺字段的 VBA 文件。
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def generate(self, template: TemplateDefinition, parameters: dict[str, Any]) -> GeneratedMacro:
        macro_template_path = self.macro_templates_dir / template.macro_template
        if not macro_template_path.exists():
            raise FileNotFoundError(f"Macro template not found: {macro_template_path}")

        jinja_template = self._env.get_template(template.macro_template)
        # 渲染上下文除了业务参数外，也会带上模板名和生成时间，
        # 便于宏里做最基础的元信息写入。
        render_context = {
            **parameters,
            "template_name": template.name,
            "generated_at": datetime.utcnow().isoformat(),
        }
        body = jinja_template.render(**render_context)

        # 宏文件单独加时间戳命名，可以避免一轮调试覆盖上一轮输出，
        # 也方便你回看某次执行到底用了哪份宏。
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        macro_file = self.output_macro_dir / f"{template.name}_{stamp}.swp"
        macro_file.write_text(body, encoding="utf-8")

        return GeneratedMacro(
            template_name=template.name,
            macro_path=macro_file,
            macro_source_path=macro_template_path,
        )
