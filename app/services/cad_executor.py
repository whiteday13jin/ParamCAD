from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

from app.core.models import ExecutionResult


class DryRunExecutor:
    def execute(
        self,
        template_name: str,
        parameters: dict[str, Any],
        model_template_path: Path,
        macro_path: Path,
        output_part_path: Path,
        output_drawing_path: Path | None = None,
    ) -> ExecutionResult:
        output_part_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "note": "dry-run mode: no real CAD execution was performed",
            "template_name": template_name,
            "parameters": parameters,
            "model_template_path": str(model_template_path),
            "macro_path": str(macro_path),
            "output_part_path": str(output_part_path),
            "output_drawing_path": str(output_drawing_path) if output_drawing_path else None,
        }
        output_part_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        if output_drawing_path is not None:
            output_drawing_path.parent.mkdir(parents=True, exist_ok=True)
            output_drawing_path.write_text(
                "dry-run drawing placeholder",
                encoding="utf-8",
            )

        return ExecutionResult(
            success=True,
            message="Dry-run execution completed.",
            part_path=output_part_path,
            drawing_path=output_drawing_path,
        )


class SolidWorksExecutor:
    def __init__(
        self,
        visible: bool = False,
        binding_path: Path | None = None,
    ):
        self.visible = visible
        self.binding_path = binding_path
        self._bindings_cache: dict[str, list[dict[str, Any]]] | None = None

    def execute(
        self,
        template_name: str,
        parameters: dict[str, Any],
        model_template_path: Path,
        macro_path: Path,
        output_part_path: Path,
        output_drawing_path: Path | None = None,
    ) -> ExecutionResult:
        try:
            import pythoncom  # type: ignore
            import win32com.client  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "pywin32 is required for real SolidWorks execution. Install with: pip install pywin32"
            ) from exc

        if not model_template_path.exists():
            raise FileNotFoundError(f"SolidWorks template model not found: {model_template_path}")

        sw_app = win32com.client.Dispatch("SldWorks.Application")
        sw_app.Visible = self.visible

        model = None
        try:
            errors = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            warnings = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            model = sw_app.OpenDoc6(
                str(model_template_path),
                1,
                1,
                "",
                errors,
                warnings,
            )
            if model is None:
                raise RuntimeError("Failed to open SolidWorks model template")

            bodies_before = self._solid_body_count(model)
            if bodies_before == 0:
                self._build_default_geometry(model, template_name, parameters)
                geometry_status = "Template was empty, built fallback base geometry."
            else:
                geometry_status = "Template bodies detected."

            binding_status = self._apply_parameter_bindings(
                model=model,
                template_name=template_name,
                parameters=parameters,
            )

            macro_status = self._run_macro_best_effort(sw_app, macro_path)

            model.ForceRebuild3(False)
            bodies_after = self._solid_body_count(model)
            if bodies_after == 0:
                raise RuntimeError(
                    "Model rebuild resulted in zero solid bodies. "
                    "Please adjust parameters or template constraints."
                )

            output_part_path.parent.mkdir(parents=True, exist_ok=True)
            model.SaveAs3(str(output_part_path), 0, 0)
            if not output_part_path.exists():
                raise RuntimeError(f"Failed to save part to {output_part_path}")

            if output_drawing_path is not None:
                output_drawing_path.parent.mkdir(parents=True, exist_ok=True)
                output_drawing_path.write_text(
                    "Drawing export placeholder: integrate template drawing flow here.",
                    encoding="utf-8",
                )

            message = " ".join([geometry_status, binding_status, macro_status]).strip()
            return ExecutionResult(
                success=True,
                message=message,
                part_path=output_part_path,
                drawing_path=output_drawing_path,
            )
        finally:
            if model is not None:
                sw_app.CloseDoc(model.GetTitle)

    def _apply_parameter_bindings(
        self,
        model: Any,
        template_name: str,
        parameters: dict[str, Any],
    ) -> str:
        template_bindings = self._load_bindings().get(template_name, [])
        if not template_bindings:
            return "No parameter bindings configured for this template."

        applied = 0
        missing_dims: list[str] = []
        bad_values: list[str] = []

        for item in template_bindings:
            param_keys = []
            key = item.get("param")
            if isinstance(key, str) and key:
                param_keys.append(key)
            aliases = item.get("aliases", [])
            if isinstance(aliases, list):
                param_keys.extend([a for a in aliases if isinstance(a, str) and a])
            if not param_keys:
                continue

            raw_value = None
            for k in param_keys:
                if k in parameters:
                    raw_value = parameters[k]
                    break
            if raw_value is None:
                continue

            unit = str(item.get("unit", "mm")).lower()
            converted = self._convert_value(raw_value, unit)
            if converted is None:
                bad_values.append(f"{param_keys[0]}={raw_value}")
                continue

            targets = item.get("targets", [])
            if not isinstance(targets, list):
                continue
            for dim_name in targets:
                if not isinstance(dim_name, str) or not dim_name:
                    continue
                if self._set_dimension(model, dim_name, converted):
                    applied += 1
                else:
                    missing_dims.append(dim_name)

        status = f"Bindings applied: {applied} dimension writes."
        if missing_dims:
            status += f" Missing dimensions: {len(missing_dims)}."
        if bad_values:
            status += f" Skipped invalid values: {', '.join(bad_values)}."
        return status

    def _load_bindings(self) -> dict[str, list[dict[str, Any]]]:
        if self._bindings_cache is not None:
            return self._bindings_cache

        if self.binding_path is None or not self.binding_path.exists():
            self._bindings_cache = {}
            return self._bindings_cache

        payload = json.loads(self.binding_path.read_text(encoding="utf-8-sig"))
        result: dict[str, list[dict[str, Any]]] = {}
        for k, v in payload.items():
            if isinstance(k, str) and isinstance(v, list):
                result[k] = [x for x in v if isinstance(x, dict)]
        self._bindings_cache = result
        return result

    @staticmethod
    def _set_dimension(model: Any, dim_name: str, value: float) -> bool:
        try:
            dim = model.Parameter(dim_name)
            if dim is None:
                return False
            dim.SystemValue = float(value)
            return True
        except Exception:
            return False

    @staticmethod
    def _convert_value(raw_value: Any, unit: str) -> float | None:
        try:
            numeric = float(raw_value)
        except Exception:
            return None

        if unit == "mm":
            return numeric / 1000.0
        if unit == "count":
            return float(max(1, int(round(numeric))))
        if unit == "deg":
            return math.radians(numeric)
        return numeric

    @staticmethod
    def _solid_body_count(model: Any) -> int:
        try:
            bodies = model.GetBodies2(0, False)
            return 0 if bodies is None else len(bodies)
        except Exception:
            return 0

    def _build_default_geometry(self, model: Any, template_name: str, parameters: dict[str, Any]) -> None:
        if template_name == "flange_connector_plate":
            self._create_flange_plate(model, parameters)
        elif template_name == "sheet_metal_cover":
            self._create_sheet_cover(model, parameters)
        else:
            self._create_mount_block(model, parameters)

    @staticmethod
    def _mm(value: Any, fallback: float) -> float:
        try:
            return float(value) / 1000.0
        except Exception:
            return fallback / 1000.0

    def _create_mount_block(self, model: Any, p: dict[str, Any]) -> None:
        length = self._mm(p.get("length"), 160)
        width = self._mm(p.get("width"), 72)
        height = self._mm(p.get("height"), 50)

        sm = model.SketchManager
        fm = model.FeatureManager
        sm.InsertSketch(True)
        sm.CreateCenterRectangle(0.0, 0.0, 0.0, length / 2, width / 2, 0.0)
        sm.InsertSketch(True)
        fm.FeatureExtrusion2(
            True,
            False,
            False,
            0,
            0,
            height,
            0.0,
            False,
            False,
            False,
            False,
            0.0,
            0.0,
            False,
            False,
            False,
            False,
            True,
            True,
            True,
            0,
            0,
            False,
        )

    def _create_flange_plate(self, model: Any, p: dict[str, Any]) -> None:
        outer_d = self._mm(p.get("outer_diameter"), 200)
        inner_d = self._mm(p.get("inner_diameter"), 90)
        boss_h = self._mm(p.get("boss_height"), 8)

        sm = model.SketchManager
        fm = model.FeatureManager
        sm.InsertSketch(True)
        sm.CreateCircleByRadius(0.0, 0.0, 0.0, max(outer_d / 2, 0.001))
        sm.CreateCircleByRadius(0.0, 0.0, 0.0, max(inner_d / 2, 0.0002))
        sm.InsertSketch(True)
        fm.FeatureExtrusion2(
            True,
            False,
            False,
            0,
            0,
            max(boss_h, 0.001),
            0.0,
            False,
            False,
            False,
            False,
            0.0,
            0.0,
            False,
            False,
            False,
            False,
            True,
            True,
            True,
            0,
            0,
            False,
        )

    def _create_sheet_cover(self, model: Any, p: dict[str, Any]) -> None:
        length = self._mm(p.get("length"), 240)
        width = self._mm(p.get("width"), 140)
        height = self._mm(p.get("height"), 100)

        sm = model.SketchManager
        fm = model.FeatureManager
        sm.InsertSketch(True)
        sm.CreateCenterRectangle(0.0, 0.0, 0.0, length / 2, width / 2, 0.0)
        sm.InsertSketch(True)
        fm.FeatureExtrusion2(
            True,
            False,
            False,
            0,
            0,
            max(height, 0.001),
            0.0,
            False,
            False,
            False,
            False,
            0.0,
            0.0,
            False,
            False,
            False,
            False,
            True,
            True,
            True,
            0,
            0,
            False,
        )

    @staticmethod
    def _run_macro_best_effort(sw_app: object, macro_path: Path) -> str:
        """Try macro only when explicitly enabled; otherwise skip to avoid modal popup loops."""
        if os.getenv("PARAMCAD_ENABLE_SW_MACRO", "").lower() not in {"1", "true", "yes"}:
            return "Macro execution skipped (default safe mode)."

        if not macro_path.exists():
            return "Macro file missing. Continued without macro execution."

        try:
            import pythoncom  # type: ignore
            import win32com.client  # type: ignore
        except ImportError:
            return "Macro dependencies unavailable. Continued without macro execution."

        candidates = [
            ("main", ""),
            ("Module1", "main"),
            ("", "main"),
            ("Main", "main"),
        ]

        last_error_code = None
        for module_name, proc_name in candidates:
            try:
                err_code = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
                run_ok = sw_app.RunMacro2(str(macro_path), module_name, proc_name, 0, err_code)
                if run_ok:
                    return f"Macro executed with module='{module_name}' proc='{proc_name}'."
                last_error_code = err_code.value
            except Exception:
                continue

        return (
            "Macro execution failed in best-effort mode; model was saved from template anyway. "
            f"Last macro error code: {last_error_code}"
        )
