# 模板可行性与参数清单（基于已上传 3 个零件）

## 总结

- 三个模板均可用：都能在 SolidWorks 中通过 COM 打开，且每个都有 1 个实体体（非空模型）。
- 已做标准化处理：
- 文件已复制到 `static/model_templates/` 并统一英文文件名。
- 法兰盘关键特征已重命名（`BaseRevolve` / `CenterRevCut` / `PatternAxis` / `BoltCirclePattern`）。
- 风险点：当前尚未接入“按参数写回这些尺寸句柄”的执行代码；本清单是下一步接入的映射依据。

## 1) 电机支架 `motor_mount_bracket.SLDPRT`

### 建议核心参数（第一批）

- `base_length_mm` -> `D1@Sketch1@motor_mount_bracket.Part`
- `base_width_mm` -> `D2@Sketch1@motor_mount_bracket.Part`
- `base_height_mm` -> `D1@BasePlateExtrude@motor_mount_bracket.Part`
- `mount_hole_d_mm` -> `D4~D8@Sketch1@motor_mount_bracket.Part`（建议联动同值）
- `pocket_size_x_mm` -> `D1@Sketch2@motor_mount_bracket.Part`
- `pocket_size_y_mm` -> `D2@Sketch2@motor_mount_bracket.Part`

### 可扩展参数（第二批）

- `featureop3_depth_mm` -> `D1@FeatureOp3@motor_mount_bracket.Part`
- `featureop4_depth_mm` -> `D1@FeatureOp4@motor_mount_bracket.Part`
- `featureop5_depth_mm` -> `D1@FeatureOp5@motor_mount_bracket.Part`
- `featureop6_depth_mm` -> `D1@FeatureOp6@motor_mount_bracket.Part`

### 建议自定义操作

- 新增安装孔（孔径、数量、阵列间距、边距）
- 指定边缘圆角（半径、目标边集合）
- 增加减重槽/开窗（位置+尺寸）
- 翻转某一切除方向或深度

## 2) 法兰盘 `flange_connector_plate.SLDPRT`

### 建议核心参数（第一批）

- `outer_diameter_mm` -> `D@BaseSketch@flange_connector_plate.Part`
- `inner_diameter_mm` -> `DD@BaseSketch@flange_connector_plate.Part`
- `thickness_mm` -> `C@BaseSketch@flange_connector_plate.Part`
- `boss_height_mm` -> `H1@BaseSketch@flange_connector_plate.Part`
- `bolt_count` -> `D1@BoltCirclePattern@flange_connector_plate.Part`（数量，无单位）

### 可扩展参数（第二批）

- `bolt_circle_diameter_mm` -> `K@CutSketch@flange_connector_plate.Part`
- `local_cut_depth_mm` -> `L@CutSketch@flange_connector_plate.Part`
- `local_cut_width_mm` -> `n@CutSketch@flange_connector_plate.Part`

### 建议自定义操作

- 增加/减少螺栓孔数与孔径
- 法兰某面反向切除（深度、轮廓）
- 增加密封槽（旋转切除）
- 增加倒角/圆角（指定边）

## 3) 钣金外壳 `sheet_metal_cover.SLDPRT`

### 建议核心参数（第一批）

- `cover_length_mm` -> `D1@Sketch1@sheet_metal_cover.Part`
- `cover_width_mm` -> `D2@Sketch1@sheet_metal_cover.Part`
- `cover_height_mm` -> `D3@Sketch1@sheet_metal_cover.Part`
- `wall_thickness_mm` -> `D1@CoverShell@sheet_metal_cover.Part`

### 可扩展参数（第二批）

- `base_extrude_depth_mm` -> `D1@CoverBaseExtrude@sheet_metal_cover.Part`

### 建议自定义操作

- 增加散热孔阵列（孔径/列数/行数/间距）
- 新增开窗（矩形/圆角矩形）
- 安装孔位（四角、边中点、指定坐标）
- 边缘圆角/倒角

## 备注与实现建议

- SolidWorks API 的长度单位是米，输入一般是毫米，写回时需统一 `mm -> m`。
- `Revolution`/`Pattern` 中部分维度为角度或无单位计数，不能按毫米直接处理。
- 建议先做“第一批核心参数”写回，稳定后再接“第二批 + 自定义操作”。
- 自定义操作建议结构化：先把备注解析为 `custom_ops[]`，再执行（避免自由文本直接改 CAD）。
