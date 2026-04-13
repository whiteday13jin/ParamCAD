from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib import error, request


@dataclass
class LLMSettings:
    api_key: str
    model: str
    base_url: str
    timeout_seconds: float

    @classmethod
    def from_env(cls) -> "LLMSettings":
        # 这里优先从环境变量拿配置，让本地开发、桌面启动、服务部署都能复用同一套代码。
        api_key = os.getenv("PARAMCAD_LLM_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
        if not api_key:
            raise RuntimeError("缺少 LLM API Key，请先配置 PARAMCAD_LLM_API_KEY 或 DASHSCOPE_API_KEY。")

        model = os.getenv("PARAMCAD_LLM_MODEL", "qwen-plus").strip() or "qwen-plus"
        base_url = os.getenv(
            "PARAMCAD_LLM_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ).strip()
        timeout_seconds = float(os.getenv("PARAMCAD_LLM_TIMEOUT_SECONDS", "45"))
        return cls(
            api_key=api_key,
            model=model,
            base_url=base_url.rstrip("/"),
            timeout_seconds=timeout_seconds,
        )


class OpenAICompatibleLLMClient:
    def __init__(self, settings: LLMSettings):
        self.settings = settings

    def chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.1,
    ) -> str:
        # 这里故意只实现最小化的 OpenAI 兼容 chat 接口，
        # 让 planner 只关心“给消息、拿文本”，而不关心底层 HTTP 细节。
        payload = {
            "model": self.settings.model,
            "messages": messages,
            "temperature": temperature,
        }
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url=f"{self.settings.base_url}/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.settings.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM 接口返回 HTTP {exc.code} 错误：{detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"LLM 网络请求失败：{exc}") from exc

        data = json.loads(raw)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"LLM 返回的数据结构不符合预期：{raw}") from exc


def extract_first_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        return json.loads(text)

    # 真实模型经常会输出“解释 + JSON”或代码块包裹的 JSON。
    # 这里手动扫描第一个完整对象，是为了让上层 planner 仍能稳定消费结构化结果。
    start = text.find("{")
    if start < 0:
        raise ValueError("LLM 返回内容中未包含可解析的 JSON 对象")

    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : idx + 1])

    raise ValueError("LLM 返回了不完整的 JSON 对象")
