from __future__ import annotations

import re

PARAM_LABELS: dict[str, str] = {
    "length": "长度",
    "width": "宽度",
    "height": "高度",
    "plate_thickness": "板厚",
    "hole_diameter": "孔径",
    "hole_count": "孔数",
    "hole_spacing": "孔距",
    "fillet_radius": "圆角半径",
    "outer_diameter": "外径",
    "inner_diameter": "内径",
    "boss_height": "凸台高度",
    "bend_radius": "折弯半径",
    "mounting_holes": "安装孔数量",
    "cutout_positions": "开孔位置",
}

TEMPLATE_LABELS: dict[str, str] = {
    "motor_mount_bracket": "电机安装支架",
    "flange_connector_plate": "法兰连接板",
    "sheet_metal_cover": "钣金外壳",
}


def param_text(key: str) -> str:
    zh = PARAM_LABELS.get(key)
    return f"{zh}（{key}）" if zh else key


def template_text(name: str) -> str:
    zh = TEMPLATE_LABELS.get(name)
    return f"{zh}（{name}）" if zh else name


def localize_message(raw: str, template_name: str | None = None) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""

    # 这一层把“内部统一错误文本”翻译成更适合中文界面显示的话术。
    # 好处是：后端内部仍能保持相对统一的英文/技术信息，而 UI 不用直接暴露生硬原文。
    if text in {
        "部分已声明参数尚未稳定接入当前 SolidWorks 尺寸绑定。",
        "部分必填参数当前仍会参与校验，但修改它们未必会真实影响模型。",
        "LLM 提案服务当前不可用",
        "LLM 提案结果解析失败",
    }:
        return text

    if text == "Validation failed":
        return "参数校验失败"
    if text == "Template not found":
        return "未找到模板"
    if text == "CAD execution failed":
        return "CAD 执行失败"

    match = re.match(r"^Missing required parameters:\s*(.+)$", text)
    if match:
        keys = [param_text(item.strip()) for item in match.group(1).split(",") if item.strip()]
        return f"缺少必填参数：{'、'.join(keys)}"

    match = re.match(r"^Parameter '([^']+)' cannot be empty$", text)
    if match:
        return f"参数 {param_text(match.group(1))} 不能为空"

    match = re.match(r"^Parameter '([^']+)' must be numeric$", text)
    if match:
        return f"参数 {param_text(match.group(1))} 必须是数字"

    match = re.match(r"^Parameter '([^']+)' must be an integer$", text)
    if match:
        return f"参数 {param_text(match.group(1))} 必须是整数"

    match = re.match(r"^Parameter '([^']+)'=([-0-9.]+) is lower than min=([-0-9.]+)$", text)
    if match:
        return f"参数 {param_text(match.group(1))}={match.group(2)} 低于最小值 {match.group(3)}"

    match = re.match(r"^Parameter '([^']+)'=([-0-9.]+) is higher than max=([-0-9.]+)$", text)
    if match:
        return f"参数 {param_text(match.group(1))}={match.group(2)} 高于最大值 {match.group(3)}"

    match = re.match(r"^Unknown parameters for template '([^']+)':\s*(.+)$", text)
    if match:
        template_display = template_text(match.group(1))
        return f"{template_display} 存在当前模板不支持的参数：{match.group(2)}"

    match = re.match(
        r"^Parameter '([^']+)' is accepted by the template schema, but it is not connected to the active SolidWorks executor yet\.$",
        text,
    )
    if match:
        return f"参数 {param_text(match.group(1))} 当前只是模板字段，尚未稳定接入执行器"

    match = re.match(
        r"^Template '([^']+)' is currently marked as support_level=([^.]*)\. Prefer dry-run or manual review before relying on real CAD output\.$",
        text,
    )
    if match:
        template_display = template_text(match.group(1))
        return f"{template_display} 当前处于部分支持阶段，建议先 dry-run 或人工复核后再依赖真实 CAD 输出"

    match = re.match(
        r"^Hole array span\s+([-0-9.]+)\s+exceeds allowed span\s+([-0-9.]+)\s+on\s+'([^']+)'\s+\(hole_count=([-0-9.]+), hole_spacing=([-0-9.]+), hole_diameter=([-0-9.]+), required_([^>=]+)>=([-0-9.]+)\)$",
        text,
    )
    if match:
        return (
            f"孔阵列总跨度 {match.group(1)} 超过 {param_text(match.group(3))} 允许跨度 {match.group(2)}，"
            f"当前组合为 孔数={match.group(4)}、孔距={match.group(5)}、孔径={match.group(6)}，"
            f"建议至少满足 {match.group(7)} >= {match.group(8)}"
        )

    if text == "inner_diameter must be smaller than outer_diameter":
        return "内径（inner_diameter）必须小于外径（outer_diameter）"
    if text == "hole_count must be >= 1":
        return "孔数（hole_count）必须大于等于 1"
    if text == "hole_spacing (bolt circle diameter) must be smaller than outer_diameter":
        return "孔中心圆直径（hole_spacing）必须小于外径（outer_diameter）"
    if text == "bolt circle + hole diameter exceeds outer diameter envelope":
        return "孔中心圆直径与孔径组合超出外径包络，请减小孔径或孔中心圆直径"
    if text == "bolt circle diameter is too small for the inner diameter and hole diameter combination":
        return "孔中心圆直径过小，当前内径与孔径组合会发生冲突"
    if text == "bolt circle and hole diameter are close to inner diameter; check wall thickness near holes.":
        return "孔中心圆与孔径已经逼近内径，请关注孔附近壁厚"
    if text == "bend_radius is smaller than plate_thickness. This may fail for real sheet-metal rules.":
        return "折弯半径小于板厚，真实钣金规则下可能失败"
    if text == "hole_diameter is smaller than plate_thickness, machining/manufacturing may be difficult.":
        return "孔径小于板厚，加工制造可能较困难"

    if template_name and text.startswith(f"{template_name} "):
        return text
    return text


def localize_messages(messages: list[str], template_name: str | None = None) -> list[str]:
    result: list[str] = []
    for message in messages:
        localized = localize_message(message, template_name)
        if localized:
            result.append(localized)
    return result
