from __future__ import annotations

import json
from pathlib import Path

from .models import TemplateDefinition


class TemplateManager:
    def __init__(self, registry_path: Path):
        self.registry_path = registry_path
        self._cache: dict[str, TemplateDefinition] = {}

    def load(self) -> dict[str, TemplateDefinition]:
        if self._cache:
            # 模板定义在一次运行里通常是静态的，所以这里缓存后可以避免重复读盘与重复反序列化。
            return self._cache

        if not self.registry_path.exists():
            raise FileNotFoundError(f"Template registry not found: {self.registry_path}")

        payload = json.loads(self.registry_path.read_text(encoding="utf-8-sig"))
        templates: dict[str, TemplateDefinition] = {}
        for key, value in payload.items():
            # 这里把 JSON 配置提升成强类型对象。
            # 后面的调用方拿到的就不再是松散字典，而是有明确字段约束的模板定义。
            templates[key] = TemplateDefinition(name=key, **value)

        self._cache = templates
        return templates

    def get(self, template_name: str) -> TemplateDefinition:
        templates = self.load()
        if template_name not in templates:
            # 模板不存在要在尽可能靠前的位置失败，
            # 避免把“选错模板”拖到更后面的校验或 CAD 阶段才暴露。
            known = ", ".join(sorted(templates.keys()))
            raise KeyError(f"Unknown template '{template_name}'. Known templates: {known}")
        return templates[template_name]
