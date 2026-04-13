from __future__ import annotations

from typing import Any

from .models import TemplateDefinition, ValidationResult


class Validator:
    def validate(
        self,
        template: TemplateDefinition,
        parameters: dict[str, Any],
        executable_parameters: set[str] | None = None,
    ) -> ValidationResult:
        # validate 的任务不是“做几个 if 判断”这么简单，
        # 而是把用户输入收敛成一组尽量可靠、可继续进入 CAD 阶段的参数。
        merged: dict[str, Any] = dict(parameters)
        defaults_applied: dict[str, Any] = {}
        declared_keys = self._declared_keys(template)

        errors: list[str] = []
        warnings: list[str] = []

        unknown = sorted(set(parameters) - declared_keys)
        if unknown:
            # 未声明字段直接报错，因为这通常意味着输入拼错、
            # 或者调用方误以为某个参数已经被当前模板支持。
            errors.append(f"Unknown parameters for template '{template.name}': {', '.join(unknown)}")

        if executable_parameters is not None:
            inactive_supplied = sorted(
                key for key in parameters if key in declared_keys and key not in executable_parameters
            )
            for key in inactive_supplied:
                # 这里只给 warning 不给 error。
                # 原因是这些参数在 schema 上是合法的，只是当前执行器还未真正接通。
                warnings.append(
                    f"Parameter '{key}' is accepted by the template schema, "
                    "but it is not connected to the active SolidWorks executor yet."
                )

        for key, value in template.defaults.items():
            if key not in merged:
                # 默认值补全放在“必填检查”前面，这样 required 字段可以通过默认值被满足。
                merged[key] = value
                defaults_applied[key] = value

        missing = [key for key in template.required if key not in merged]
        if missing:
            errors.append(f"Missing required parameters: {', '.join(missing)}")

        normalized: dict[str, Any] = {}
        for key, value in merged.items():
            if isinstance(value, str):
                stripped = value.strip()
                if stripped == "":
                    errors.append(f"Parameter '{key}' cannot be empty")
                    continue
                # 字符串数字尽量在这里提前转成数值，
                # 后面的 bounds 和关系校验就可以统一按数字处理。
                value = self._parse_number_if_possible(stripped)
            normalized[key] = value

        # 某些参数虽然输入来源可能是 float，但业务上必须是整数，例如孔数。
        self._validate_integer_parameters(normalized, errors)

        for key, rule in template.bounds.items():
            if key not in normalized:
                continue
            raw_value = normalized[key]
            if not isinstance(raw_value, (int, float)):
                errors.append(f"Parameter '{key}' must be numeric")
                continue

            min_value = rule.get("min")
            max_value = rule.get("max")
            if min_value is not None and raw_value < min_value:
                errors.append(f"Parameter '{key}'={raw_value} is lower than min={min_value}")
            if max_value is not None and raw_value > max_value:
                errors.append(f"Parameter '{key}'={raw_value} is higher than max={max_value}")

        # 通用 bounds 之后再跑模板专属关系校验。
        # 前者处理“单个值是否合法”，后者处理“多个参数组合起来是否合理”。
        self._run_custom_checks(template.name, normalized, errors, warnings)

        return ValidationResult(
            template=template.name,
            normalized_parameters=normalized,
            defaults_applied=defaults_applied,
            warnings=warnings,
            errors=errors,
        )

    @staticmethod
    def _parse_number_if_possible(value: str) -> Any:
        try:
            if "." in value:
                return float(value)
            return int(value)
        except ValueError:
            return value

    def _run_custom_checks(
        self,
        template_name: str,
        params: dict[str, Any],
        errors: list[str],
        warnings: list[str],
    ) -> None:
        if template_name == "motor_mount_bracket":
            # 电机支架当前实质上按固定孔布局工作，
            # 所以长度、孔距、孔径之间需要做组合关系检查。
            self._check_hole_array_span(params, "length", errors)
            self._check_hole_vs_thickness(params, warnings)

        elif template_name == "flange_connector_plate":
            outer_d = params.get("outer_diameter")
            inner_d = params.get("inner_diameter")
            if isinstance(outer_d, (int, float)) and isinstance(inner_d, (int, float)):
                if inner_d >= outer_d:
                    errors.append("inner_diameter must be smaller than outer_diameter")
            hole_count = params.get("hole_count")
            hole_d = params.get("hole_diameter")
            bolt_circle_d = params.get("hole_spacing")

            if isinstance(hole_count, (int, float)) and hole_count < 1:
                errors.append("hole_count must be >= 1")

            if all(isinstance(v, (int, float)) for v in [outer_d, hole_d, bolt_circle_d]):
                # 这几条规则本质上是在检查“孔阵列是否仍位于法兰实体包络内”。
                if bolt_circle_d >= outer_d:
                    errors.append("hole_spacing (bolt circle diameter) must be smaller than outer_diameter")
                if bolt_circle_d + hole_d > outer_d:
                    errors.append("bolt circle + hole diameter exceeds outer diameter envelope")

            if all(isinstance(v, (int, float)) for v in [inner_d, hole_d, bolt_circle_d]):
                # 这里检查的是孔阵列与内孔之间的剩余壁厚关系。
                if bolt_circle_d - hole_d <= inner_d:
                    errors.append(
                        "bolt circle diameter is too small for the inner diameter and hole diameter combination"
                    )
                elif bolt_circle_d - hole_d < inner_d + 4:
                    warnings.append(
                        "bolt circle and hole diameter are close to inner diameter; check wall thickness near holes."
                    )

        elif template_name == "sheet_metal_cover":
            bend_r = params.get("bend_radius")
            plate_t = params.get("plate_thickness")
            if isinstance(bend_r, (int, float)) and isinstance(plate_t, (int, float)):
                # 这里先给 warning 而不是直接禁掉，
                # 因为不同钣金规则和模板细节下，能否成功并不完全由这一条决定。
                if bend_r < plate_t:
                    warnings.append(
                        "bend_radius is smaller than plate_thickness. This may fail for real sheet-metal rules."
                    )

    @staticmethod
    def _check_hole_array_span(params: dict[str, Any], axis_key: str, errors: list[str]) -> None:
        hole_count = params.get("hole_count")
        hole_spacing = params.get("hole_spacing")
        hole_diameter = params.get("hole_diameter")
        axis_size = params.get(axis_key)

        if not all(
            isinstance(v, (int, float))
            for v in [hole_count, hole_spacing, hole_diameter, axis_size]
        ):
            return

        array_span = (int(hole_count) - 1) * hole_spacing
        min_edge_margin = 1.5 * hole_diameter
        allowed_span = axis_size - 2 * min_edge_margin
        required_axis_size = array_span + 2 * min_edge_margin
        if array_span > allowed_span:
            # 这条错误信息刻意带上“当前组合”和“建议满足的最小尺寸”，
            # 因为它不只是告诉你错了，还告诉你大概要往哪个方向改。
            errors.append(
                f"Hole array span {array_span} exceeds allowed span {allowed_span:.2f} on '{axis_key}' "
                f"(hole_count={int(hole_count)}, hole_spacing={hole_spacing}, hole_diameter={hole_diameter}, "
                f"required_{axis_key}>={required_axis_size:.2f})"
            )

    @staticmethod
    def _check_hole_vs_thickness(params: dict[str, Any], warnings: list[str]) -> None:
        hole_diameter = params.get("hole_diameter")
        plate_t = params.get("plate_thickness")
        if isinstance(hole_diameter, (int, float)) and isinstance(plate_t, (int, float)):
            if hole_diameter < plate_t:
                warnings.append(
                    "hole_diameter is smaller than plate_thickness, machining/manufacturing may be difficult."
                )

    @staticmethod
    def _declared_keys(template: TemplateDefinition) -> set[str]:
        keys = set(template.required)
        keys.update(template.defaults.keys())
        keys.update(template.bounds.keys())
        return keys

    @staticmethod
    def _validate_integer_parameters(params: dict[str, Any], errors: list[str]) -> None:
        for key in ("hole_count", "mounting_holes"):
            if key not in params:
                continue
            value = params[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            if int(value) != value:
                errors.append(f"Parameter '{key}' must be an integer")
