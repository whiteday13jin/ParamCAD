from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.models import OutputPaths, TemplateDefinition


class OutputManager:
    def __init__(self, output_root: Path):
        self.output_root = output_root
        self.parts_dir = output_root / "parts"
        self.logs_dir = output_root / "logs"

        self.parts_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def allocate_paths(self, template: TemplateDefinition, params: dict[str, Any]) -> OutputPaths:
        summary = self._build_summary(template, params)
        prefix = f"{template.name}_{summary}"

        # 版本号不是靠全局计数器，而是扫描现有产物得到。
        # 这样即使多次单独运行，也能自然避免覆盖历史结果。
        version = self._next_version(prefix)
        basename = f"{prefix}_v{version}"

        part_path = self.parts_dir / f"{basename}.SLDPRT"
        drawing_path = self.parts_dir / f"{basename}.SLDDRW"
        log_path = self.logs_dir / f"{basename}.log.json"

        return OutputPaths(
            version=version,
            part_path=part_path,
            drawing_path=drawing_path,
            log_path=log_path,
        )

    def write_log(self, log_path: Path, payload: dict[str, Any]) -> None:
        payload = dict(payload)
        # 这里额外写 logged_at，是为了把“业务生成时间”和“日志落盘时间”区分开。
        payload["logged_at"] = datetime.utcnow().isoformat()
        log_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _build_summary(self, template: TemplateDefinition, params: dict[str, Any]) -> str:
        # summary_keys 允许模板自己决定文件名里最值得保留的参数摘要，
        # 这样输出文件在目录里会更容易人工辨认。
        keys = template.summary_keys if template.summary_keys else sorted(params.keys())[:4]
        tokens = []
        for key in keys:
            if key not in params:
                continue
            value = params[key]
            token = f"{self._abbr(key)}{value}"
            tokens.append(self._slugify(token))
        return "_".join(tokens) if tokens else "default"

    def _next_version(self, prefix: str) -> int:
        pattern = re.compile(rf"^{re.escape(prefix)}_v(?P<v>\d+)\.SLDPRT$", re.IGNORECASE)
        max_v = 0
        for file in self.parts_dir.glob(f"{prefix}_v*.SLDPRT"):
            match = pattern.match(file.name)
            if not match:
                continue
            max_v = max(max_v, int(match.group("v")))
        return max_v + 1

    @staticmethod
    def _abbr(key: str) -> str:
        return "".join(part[0].upper() for part in key.split("_"))

    @staticmethod
    def _slugify(text: str) -> str:
        text = str(text)
        text = re.sub(r"\s+", "", text)
        text = re.sub(r"[^A-Za-z0-9_.-]", "", text)
        return text
