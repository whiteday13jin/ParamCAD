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
            return self._cache

        if not self.registry_path.exists():
            raise FileNotFoundError(f"Template registry not found: {self.registry_path}")

        payload = json.loads(self.registry_path.read_text(encoding="utf-8-sig"))
        templates: dict[str, TemplateDefinition] = {}
        for key, value in payload.items():
            templates[key] = TemplateDefinition(name=key, **value)

        self._cache = templates
        return templates

    def get(self, template_name: str) -> TemplateDefinition:
        templates = self.load()
        if template_name not in templates:
            known = ", ".join(sorted(templates.keys()))
            raise KeyError(f"Unknown template '{template_name}'. Known templates: {known}")
        return templates[template_name]
