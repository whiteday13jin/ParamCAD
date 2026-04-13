from __future__ import annotations

import json
from pathlib import Path

from .models import TemplateDefinition


class TemplateCapabilityInspector:
    def __init__(self, binding_path: Path):
        self.binding_path = binding_path
        self._bindings_cache: dict[str, list[dict[str, object]]] | None = None

    def describe(self, template: TemplateDefinition) -> dict[str, object]:
        # 这层做的不是“参数定义”，而是“真实可执行能力盘点”。
        # declared 来自模板 schema，bound 来自 SolidWorks 尺寸绑定，两者不一定相同。
        declared = self._declared_parameters(template)
        bound = self._bound_parameters(template.name)
        inactive = sorted(declared - bound)
        required_inactive = sorted(set(template.required) - bound)

        notes: list[str] = []
        if inactive:
            notes.append(
                "部分已声明参数尚未稳定接入当前 SolidWorks 尺寸绑定。"
            )
        if required_inactive:
            notes.append(
                "部分必填参数当前仍会参与校验，但修改它们未必会真实影响模型。"
            )

        return {
            # declared_parameters: 模板层面声明了什么
            # effective_parameters: 当前执行器真正能稳定写入什么
            # inactive_parameters: schema 有，但还没接通执行器的字段
            "declared_parameters": sorted(declared),
            "effective_parameters": sorted(bound),
            "inactive_parameters": inactive,
            "required_inactive_parameters": required_inactive,
            "notes": notes,
        }

    def executable_parameters(self, template: TemplateDefinition) -> set[str]:
        return self._bound_parameters(template.name)

    def _declared_parameters(self, template: TemplateDefinition) -> set[str]:
        keys = set(template.required)
        keys.update(template.defaults.keys())
        keys.update(template.bounds.keys())
        return keys

    def _bound_parameters(self, template_name: str) -> set[str]:
        bindings = self._load_bindings().get(template_name, [])
        params: set[str] = set()
        for item in bindings:
            param = item.get("param")
            if isinstance(param, str) and param:
                # 这里关注的是“哪个业务参数被接上了”，
                # 而不是具体接到了多少个尺寸句柄。
                params.add(param)
        return params

    def _load_bindings(self) -> dict[str, list[dict[str, object]]]:
        if self._bindings_cache is not None:
            return self._bindings_cache

        if not self.binding_path.exists():
            self._bindings_cache = {}
            return self._bindings_cache

        payload = json.loads(self.binding_path.read_text(encoding="utf-8-sig"))
        bindings: dict[str, list[dict[str, object]]] = {}
        for template_name, items in payload.items():
            if isinstance(template_name, str) and isinstance(items, list):
                bindings[template_name] = [item for item in items if isinstance(item, dict)]
        self._bindings_cache = bindings
        return bindings
