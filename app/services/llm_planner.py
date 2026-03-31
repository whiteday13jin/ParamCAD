from __future__ import annotations

import re
from typing import Any

from app.core.capabilities import TemplateCapabilityInspector
from app.core.message_localizer import PARAM_LABELS, TEMPLATE_LABELS, localize_messages
from app.core.models import LLMPlanResponse, LLMProposedOp, TemplateDefinition
from app.core.template_manager import TemplateManager
from app.core.validation import Validator

from .llm_client import OpenAICompatibleLLMClient, extract_first_json_object


class BaseTemplateLLMPlanner:
    template_name: str = ""
    explicit_patterns: list[tuple[str, str, bool]] = []
    unsupported_feature_keywords: list[str] = []
    unsupported_feature_specs: list[dict[str, Any]] = []

    def __init__(
        self,
        template_manager: TemplateManager,
        capability_inspector: TemplateCapabilityInspector,
        validator: Validator,
        llm_client: OpenAICompatibleLLMClient,
    ):
        self.template_manager = template_manager
        self.capability_inspector = capability_inspector
        self.validator = validator
        self.llm_client = llm_client

    def plan(self, text: str) -> LLMPlanResponse:
        source_text = text.strip()
        template = self.template_manager.get(self.template_name)
        if not template.llm_ready:
            raise RuntimeError(f"模板 {template.name} 尚未标记为 llm_ready")

        visible_parameters = self._visible_parameters(template)
        proposed_ops = self._extract_proposed_ops(source_text)
        lowered = source_text.lower()
        if proposed_ops and not any(key.lower() in lowered for key in self._all_parameter_aliases()):
            return LLMPlanResponse(
                status="unsupported",
                template=None,
                parameter_patch={},
                explicit_parameters={},
                inferred_parameters={},
                suggested_defaults={},
                proposed_ops=proposed_ops,
                missing_or_uncertain=[],
                warnings=["已识别到当前模板稳定参数范围外的特征请求，已作为提议返回，不会直接执行。"],
                validation_errors=[],
                summary=self._unsupported_summary(template, visible_parameters),
            )

        content = self.llm_client.chat_completion(
            messages=[
                {"role": "system", "content": self._build_system_prompt(template, visible_parameters)},
                {"role": "user", "content": source_text},
            ],
            temperature=0.0,
        )
        raw_plan = extract_first_json_object(content)
        return self._normalize_response(raw_plan, source_text, template, visible_parameters)

    def _build_system_prompt(
        self,
        template: TemplateDefinition,
        visible_parameters: list[str],
    ) -> str:
        return (
            f"你是 ParamCAD 的 {template.name} 参数提案器，只能输出 JSON。"
            f"允许的参数名只有：{visible_parameters}。"
            "允许在当前模板的稳定参数集合内做最近特征归一化。"
            "例如：'外220' 可以靠到 outer_diameter=220，'凸8' 可以靠到 boss_height=8，'15厚' 可以靠到 plate_thickness=15。"
            "但只能在当前模板已支持的稳定参数里靠，不能编造新特征。"
            "如果用户同时给出稳定参数和当前模板不支持的特征，只提取稳定参数，并把状态设为 needs_confirmation。"
            "如果用户描述的是别的模板，或者只有当前模板不支持的特征，返回 unsupported。"
            "如果用户原文中已经明确给出数值，必须按原文提取，不要改写、不许调换。"
            "不要编造字段。"
            "如果某个值不够明确，不要猜，把它放进 missing_or_uncertain。"
            "返回 JSON 结构："
            '{"status":"ready|needs_confirmation|unsupported","template":"template_name|null","parameter_patch":{},'
            '"missing_or_uncertain":[],"warnings":[],"summary":"..."}。'
            f"当前默认值：{template.defaults}。"
            f"当前范围：{template.bounds}。"
            f"{self._extra_prompt_rules()}"
        )

    def _extra_prompt_rules(self) -> str:
        return ""

    def _visible_parameters(self, template: TemplateDefinition) -> list[str]:
        capability_report = self.capability_inspector.describe(template)
        return list(capability_report["effective_parameters"])

    def _unsupported_summary(self, template: TemplateDefinition, visible_parameters: list[str]) -> str:
        fields = "、".join(self._param_label(key) for key in sorted(visible_parameters))
        return f"{self._template_label(template.name)} 当前只支持稳定参数：{fields}。本次描述超出了可规划范围。"

    def _all_parameter_aliases(self) -> list[str]:
        aliases = list(PARAM_LABELS) + list(PARAM_LABELS.values())
        aliases.extend(["length", "width", "height", "thickness", "outer", "inner", "boss", "外径", "内径", "外", "内", "凸", "厚", "长", "宽", "高", "孔", "距", "圆"])
        return aliases

    def _extract_proposed_ops(self, text: str) -> list[LLMProposedOp]:
        lowered = text.lower()
        proposed: list[LLMProposedOp] = []
        for spec in self.unsupported_feature_specs:
            keywords = [str(item).lower() for item in spec.get("keywords", [])]
            if not any(keyword in lowered for keyword in keywords):
                continue
            proposed.append(
                LLMProposedOp(
                    op=str(spec["op"]),
                    label=str(spec.get("label", spec["op"])),
                    status="proposal_only",
                    reason=str(spec.get("reason", "当前仅保留为提议，不会直接执行。")),
                    arguments=self._extract_proposed_arguments(text, spec),
                )
            )
        return proposed

    def _extract_proposed_arguments(self, text: str, spec: dict[str, Any]) -> dict[str, Any]:
        arguments: dict[str, Any] = {}
        count_match = re.search(r"(\d+)\s*个", text)
        if count_match and spec.get("capture_count"):
            arguments["count"] = int(count_match.group(1))

        diameter_match = re.search(r"(?:孔径|直径)\s*[:：=]?\s*(\d+(?:\.\d+)?)", text, re.IGNORECASE)
        if diameter_match and spec.get("capture_diameter"):
            raw = diameter_match.group(1)
            arguments["diameter"] = float(raw) if "." in raw else int(raw)

        radius_match = re.search(r"(?:圆角|倒角|半径)\s*[:：=]?\s*(\d+(?:\.\d+)?)", text, re.IGNORECASE)
        if radius_match and spec.get("capture_radius"):
            raw = radius_match.group(1)
            arguments["radius"] = float(raw) if "." in raw else int(raw)

        return arguments

    def _normalize_response(
        self,
        raw_plan: dict[str, Any],
        source_text: str,
        template: TemplateDefinition,
        visible_parameters: list[str],
    ) -> LLMPlanResponse:
        allowed = set(visible_parameters)
        status = str(raw_plan.get("status", "needs_confirmation")).strip() or "needs_confirmation"
        template_name = raw_plan.get("template")
        if template_name is not None:
            template_name = str(template_name).strip() or None

        raw_patch = raw_plan.get("parameter_patch", {})
        patch: dict[str, Any] = {}
        if isinstance(raw_patch, dict):
            for key, value in raw_patch.items():
                if key not in allowed:
                    continue
                normalized_value = self._normalize_value(key, value)
                if normalized_value is not None:
                    patch[key] = normalized_value

        explicit_parameters = self._extract_explicit_values(source_text, allowed)
        patch.update(explicit_parameters)
        inferred_parameters = {key: value for key, value in patch.items() if key not in explicit_parameters}
        proposed_ops = self._extract_proposed_ops(source_text)

        missing_or_uncertain = self._normalize_missing_items(
            self._string_list(raw_plan.get("missing_or_uncertain")),
            visible_parameters,
        )
        warnings = self._string_list(raw_plan.get("warnings"))
        summary = str(raw_plan.get("summary", "")).strip()

        if status == "unsupported" and not explicit_parameters and not proposed_ops:
            return LLMPlanResponse(
                status="unsupported",
                template=None,
                parameter_patch={},
                explicit_parameters={},
                inferred_parameters={},
                suggested_defaults={},
                proposed_ops=[],
                missing_or_uncertain=[],
                warnings=[],
                validation_errors=[],
                summary=summary or self._unsupported_summary(template, visible_parameters),
            )

        if template_name not in {None, template.name}:
            warnings.append(f"模型返回了不支持的模板 '{template_name}'，已忽略并改回当前模板。")

        validation = self.validator.validate(
            template,
            patch,
            executable_parameters=set(visible_parameters),
        )

        missing_visible = [key for key in visible_parameters if key not in patch]
        suggested_defaults = {key: template.defaults[key] for key in missing_visible if key in template.defaults}
        for key, value in suggested_defaults.items():
            missing_or_uncertain.append(f"{self._param_label(key)}未明确，当前将使用默认值 {value}")

        localized_warnings = localize_messages(warnings, template.name)
        localized_warnings.extend(localize_messages(validation.warnings, template.name))
        localized_errors = localize_messages(validation.errors, template.name)
        if proposed_ops:
            localized_warnings.append("已识别到超出当前执行范围的特征请求，已作为 proposed_ops 返回，不会直接执行。")

        final_status = status
        if localized_errors or missing_or_uncertain or not patch or inferred_parameters or proposed_ops:
            final_status = "needs_confirmation"
        elif final_status not in {"ready", "needs_confirmation"}:
            final_status = "ready"

        summary_to_use = summary
        if final_status != "ready" or localized_errors or missing_or_uncertain:
            summary_to_use = ""

        return LLMPlanResponse(
            status=final_status,
            template=template.name,
            parameter_patch=patch,
            explicit_parameters=explicit_parameters,
            inferred_parameters=inferred_parameters,
            suggested_defaults=suggested_defaults,
            proposed_ops=proposed_ops,
            missing_or_uncertain=self._dedupe(missing_or_uncertain),
            warnings=self._dedupe(localized_warnings),
            validation_errors=self._dedupe(localized_errors),
            summary=summary_to_use or self._fallback_summary(
                template.name,
                explicit_parameters,
                inferred_parameters,
                suggested_defaults,
                final_status,
            ),
        )

    @staticmethod
    def _normalize_value(key: str, value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped == "":
                return None
            try:
                value = float(stripped) if "." in stripped else int(stripped)
            except ValueError:
                return None

        if key == "hole_count":
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return int(round(value))
            return None

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
        return None

    def _extract_explicit_values(self, text: str, allowed: set[str]) -> dict[str, Any]:
        extracted: dict[str, Any] = {}
        for key, pattern, as_int in self.explicit_patterns:
            if key not in allowed or key in extracted:
                continue
            match = re.search(pattern, text, re.IGNORECASE)
            if not match:
                continue
            raw = match.group(1)
            extracted[key] = int(raw) if as_int else float(raw) if "." in raw else int(raw)
        return extracted

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def _normalize_missing_items(
        self,
        items: list[str],
        visible_parameters: list[str],
    ) -> list[str]:
        visible_set = set(visible_parameters)
        normalized: list[str] = []
        proposed_terms = {
            "slot", "开槽", "槽", "开窗", "window", "cutout", "开孔",
            "安装孔", "mounting_holes", "孔数", "hole_count",
            "圆角", "倒角", "fillet", "chamfer", "密封槽", "折弯半径", "bend_radius",
        }
        for item in items:
            if item in visible_set:
                continue
            if item.strip().lower() in proposed_terms:
                continue
            normalized.append(item)
        return normalized

    @staticmethod
    def _dedupe(items: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result

    def _fallback_summary(
        self,
        template_name: str,
        explicit_parameters: dict[str, Any],
        inferred_parameters: dict[str, Any],
        suggested_defaults: dict[str, Any],
        status: str,
    ) -> str:
        if status == "unsupported":
            template = self.template_manager.get(template_name)
            visible_parameters = self._visible_parameters(template)
            return self._unsupported_summary(template, visible_parameters)

        if not explicit_parameters and not inferred_parameters:
            return f"已识别为 {self._template_label(template_name)} 相关请求，但还没有足够明确的稳定参数。"

        parts: list[str] = []
        if explicit_parameters:
            explicit_text = "、".join(
                f"{self._param_label(key)}={explicit_parameters[key]}" for key in sorted(explicit_parameters)
            )
            parts.append(f"已明确提取参数：{explicit_text}")
        if inferred_parameters:
            inferred_text = "、".join(self._param_label(key) for key in sorted(inferred_parameters))
            parts.append(f"以下参数来自模型推断，建议确认：{inferred_text}")
        if suggested_defaults:
            defaults_text = "、".join(
                f"{self._param_label(key)}={suggested_defaults[key]}" for key in sorted(suggested_defaults)
            )
            parts.append(f"以下参数未提供，将沿用默认值：{defaults_text}")
        return "；".join(parts) + "。"

    def _param_label(self, key: str) -> str:
        return PARAM_LABELS.get(key, key)

    def _template_label(self, name: str) -> str:
        return TEMPLATE_LABELS.get(name, name)


class FlangeLLMPlanner(BaseTemplateLLMPlanner):
    template_name = "flange_connector_plate"
    explicit_patterns = [
        ("outer_diameter", r"(?:外径|outer(?:\s+diameter)?)\s*[:：=]?\s*(\d+(?:\.\d+)?)", False),
        ("outer_diameter", r"外\s*(\d+(?:\.\d+)?)", False),
        ("inner_diameter", r"(?:内径|inner(?:\s+diameter)?)\s*[:：=]?\s*(\d+(?:\.\d+)?)", False),
        ("inner_diameter", r"内\s*(\d+(?:\.\d+)?)", False),
        ("plate_thickness", r"(?:板厚|厚度|thickness)\s*[:：=]?\s*(\d+(?:\.\d+)?)", False),
        ("plate_thickness", r"(?:厚|t)\s*(\d+(?:\.\d+)?)", False),
        ("plate_thickness", r"(\d+(?:\.\d+)?)\s*厚", False),
        ("boss_height", r"(?:凸台(?:高|高度)?|boss(?:\s+height)?)\s*[:：=]?\s*(\d+(?:\.\d+)?)", False),
        ("boss_height", r"凸\s*(\d+(?:\.\d+)?)", False),
        ("hole_spacing", r"(?:孔中心圆(?:直径)?|中心圆(?:直径)?|bolt\s*circle(?:\s+diameter)?)\s*[:：=]?\s*(\d+(?:\.\d+)?)", False),
        ("hole_spacing", r"(?:中心圆|圆)\s*(\d+(?:\.\d+)?)", False),
        ("hole_diameter", r"(?:孔径|hole(?:\s+diameter)?)\s*[:：=]?\s*(\d+(?:\.\d+)?)", False),
        ("hole_diameter", r"孔\s*(\d+(?:\.\d+)?)", False),
        ("hole_count", r"(\d+)\s*个孔", True),
        ("hole_count", r"(\d+)\s*个孔洞", True),
        ("hole_count", r"(\d+)\s*孔洞", True),
        ("hole_count", r"(?:孔数(?:量)?|hole\s*count)\s*[:：=]?\s*(\d+)", True),
    ]
    unsupported_feature_keywords = ["开槽", "开窗", "倒角", "自定义特征", "密封槽", "slot", "chamfer"]
    unsupported_feature_specs = [
        {"op": "add_slot", "label": "新增开槽", "keywords": ["开槽", "槽", "slot"], "reason": "当前法兰模板尚未接入开槽执行能力，只保留为提议。"},
        {"op": "add_window", "label": "新增开窗", "keywords": ["开窗", "window"], "reason": "当前法兰模板尚未接入开窗执行能力，只保留为提议。"},
        {"op": "add_chamfer", "label": "新增倒角", "keywords": ["倒角", "chamfer"], "reason": "当前法兰模板尚未接入倒角执行能力，只保留为提议。", "capture_radius": True},
        {"op": "add_seal_groove", "label": "新增密封槽", "keywords": ["密封槽"], "reason": "当前法兰模板尚未接入密封槽执行能力，只保留为提议。"},
    ]

    def _extra_prompt_rules(self) -> str:
        return (
            "重要关系规则："
            "inner_diameter 必须小于 outer_diameter；"
            "hole_spacing 必须小于 outer_diameter；"
            "hole_spacing + hole_diameter 不能超过 outer_diameter；"
            "hole_spacing - hole_diameter 必须大于 inner_diameter；"
            "boss_height 过大时容易失败。"
        )


class SheetMetalCoverLLMPlanner(BaseTemplateLLMPlanner):
    template_name = "sheet_metal_cover"
    explicit_patterns = [
        ("length", r"(?:长度|长|length)\s*[:：=]?\s*(\d+(?:\.\d+)?)", False),
        ("width", r"(?:宽度|宽|width)\s*[:：=]?\s*(\d+(?:\.\d+)?)", False),
        ("height", r"(?:高度|高|height)\s*[:：=]?\s*(\d+(?:\.\d+)?)", False),
        ("plate_thickness", r"(?:板厚|厚度|thickness)\s*[:：=]?\s*(\d+(?:\.\d+)?)", False),
        ("plate_thickness", r"(?:厚|t)\s*(\d+(?:\.\d+)?)", False),
        ("plate_thickness", r"(\d+(?:\.\d+)?)\s*厚", False),
    ]
    unsupported_feature_keywords = [
        "安装孔",
        "孔位",
        "开孔",
        "开窗",
        "cutout",
        "mounting_holes",
        "bend_radius",
        "折弯半径",
    ]
    unsupported_feature_specs = [
        {"op": "add_mounting_holes", "label": "新增安装孔", "keywords": ["安装孔", "孔位"], "reason": "当前钣金外壳模板尚未稳定支持安装孔执行，只保留为提议。", "capture_count": True, "capture_diameter": True},
        {"op": "add_cutout", "label": "新增开孔/开窗", "keywords": ["开孔", "开窗", "cutout"], "reason": "当前钣金外壳模板尚未稳定支持开孔执行，只保留为提议。"},
        {"op": "set_bend_radius", "label": "调整折弯半径", "keywords": ["bend_radius", "折弯半径"], "reason": "当前钣金外壳模板尚未稳定支持折弯半径规划，只保留为提议。", "capture_radius": True},
    ]

    def _visible_parameters(self, template: TemplateDefinition) -> list[str]:
        capability_report = self.capability_inspector.describe(template)
        hidden = set(capability_report["inactive_parameters"])
        return [key for key in capability_report["declared_parameters"] if key not in hidden]

    def _extra_prompt_rules(self) -> str:
        return (
            "当前只支持外形长度、宽度、高度和板厚。"
            "不要提 bend_radius、mounting_holes、cutout_positions。"
        )


class MotorMountLLMPlanner(BaseTemplateLLMPlanner):
    template_name = "motor_mount_bracket"
    explicit_patterns = [
        ("length", r"(?:长度|长|length)\s*[:：=]?\s*(\d+(?:\.\d+)?)", False),
        ("width", r"(?:宽度|宽|width)\s*[:：=]?\s*(\d+(?:\.\d+)?)", False),
        ("height", r"(?:高度|高|height)\s*[:：=]?\s*(\d+(?:\.\d+)?)", False),
        ("plate_thickness", r"(?:板厚|厚度|thickness)\s*[:：=]?\s*(\d+(?:\.\d+)?)", False),
        ("plate_thickness", r"(?:厚|t)\s*(\d+(?:\.\d+)?)", False),
        ("plate_thickness", r"(\d+(?:\.\d+)?)\s*厚", False),
        ("hole_diameter", r"(?:孔径|hole(?:\s+diameter)?)\s*[:：=]?\s*(\d+(?:\.\d+)?)", False),
        ("hole_diameter", r"孔\s*(\d+(?:\.\d+)?)", False),
        ("hole_spacing", r"(?:孔距|孔中心距|hole\s*spacing)\s*[:：=]?\s*(\d+(?:\.\d+)?)", False),
        ("hole_spacing", r"(?:距|中心距)\s*(\d+(?:\.\d+)?)", False),
    ]
    unsupported_feature_keywords = [
        "孔数",
        "个孔",
        "圆角",
        "倒角",
        "开槽",
        "开窗",
        "减重槽",
        "自定义特征",
        "fillet",
        "hole_count",
    ]
    unsupported_feature_specs = [
        {"op": "set_hole_count", "label": "调整孔数", "keywords": ["孔数", "个孔", "hole_count"], "reason": "当前电机支架模板按固定 4 孔布局工作，孔数只保留为提议。", "capture_count": True},
        {"op": "add_fillet", "label": "新增圆角", "keywords": ["圆角", "fillet"], "reason": "当前电机支架模板尚未接入圆角执行能力，只保留为提议。", "capture_radius": True},
        {"op": "add_chamfer", "label": "新增倒角", "keywords": ["倒角"], "reason": "当前电机支架模板尚未接入倒角执行能力，只保留为提议。", "capture_radius": True},
        {"op": "add_slot", "label": "新增开槽", "keywords": ["开槽", "减重槽"], "reason": "当前电机支架模板尚未接入槽特征执行能力，只保留为提议。"},
    ]

    def _visible_parameters(self, template: TemplateDefinition) -> list[str]:
        capability_report = self.capability_inspector.describe(template)
        hidden = set(capability_report["inactive_parameters"])
        return [key for key in capability_report["declared_parameters"] if key not in hidden]

    def _extra_prompt_rules(self) -> str:
        return (
            "当前只支持长度、宽度、高度、板厚、孔径、孔距。"
            "当前模型按固定 4 孔布局工作，不要输出 hole_count 或 fillet_radius。"
            "关键关系规则：length 必须足够容纳当前孔布局，经验上应满足 "
            "length >= 3 * hole_spacing + 3 * hole_diameter。"
        )


class ParamCADLLMPlanner:
    def __init__(
        self,
        template_manager: TemplateManager,
        capability_inspector: TemplateCapabilityInspector,
        validator: Validator,
        llm_client: OpenAICompatibleLLMClient,
    ):
        self.planners = {
            "flange_connector_plate": FlangeLLMPlanner(
                template_manager=template_manager,
                capability_inspector=capability_inspector,
                validator=validator,
                llm_client=llm_client,
            ),
            "sheet_metal_cover": SheetMetalCoverLLMPlanner(
                template_manager=template_manager,
                capability_inspector=capability_inspector,
                validator=validator,
                llm_client=llm_client,
            ),
            "motor_mount_bracket": MotorMountLLMPlanner(
                template_manager=template_manager,
                capability_inspector=capability_inspector,
                validator=validator,
                llm_client=llm_client,
            ),
        }

    def plan(self, text: str) -> LLMPlanResponse:
        planner = self._route(text)
        if planner is None:
            return LLMPlanResponse(
                status="unsupported",
                template=None,
                parameter_patch={},
                explicit_parameters={},
                inferred_parameters={},
                suggested_defaults={},
                proposed_ops=[],
                missing_or_uncertain=[],
                warnings=[],
                validation_errors=[],
                summary="当前自然语言提案仅支持法兰模板、钣金外壳模板、电机安装支架模板的稳定参数。",
            )
        return planner.plan(text)

    def _route(self, text: str) -> BaseTemplateLLMPlanner | None:
        lowered = text.lower()
        if "法兰" in text or "flange" in lowered:
            return self.planners["flange_connector_plate"]
        if any(keyword in text for keyword in ["钣金", "外壳", "罩壳"]) or "cover" in lowered:
            return self.planners["sheet_metal_cover"]
        if any(keyword in text for keyword in ["支架", "电机", "安装架"]) or "bracket" in lowered:
            return self.planners["motor_mount_bracket"]
        if any(keyword in text for keyword in ["凸台", "凸", "外径", "内径", "孔中心圆", "中心圆", "外", "内"]):
            return self.planners["flange_connector_plate"]
        if any(keyword in text for keyword in ["孔距", "中心距", "距"]) and any(keyword in text for keyword in ["长", "宽", "高", "厚"]):
            return self.planners["motor_mount_bracket"]
        return None
