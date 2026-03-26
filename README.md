# ParamCAD-SolidWorks 本地参数化零件生成器 v0.82

## 1. 项目定位

ParamCAD 是一个参数化的 CAD 模型自动生成工具，终极目标为~~统治世界~~AI独立快速完成所有非复杂零部件的作图（v99.9）。
拥有以下链路/模块：

1. 参数输入（JSON / Excel / Web）
2. 模板匹配与参数映射
3. 约束校验与默认值补全
4. SolidWorks 自动改参 + rebuild + 保存
5. 输出日志，便于工程师复核

适用对象：反复出“同类型零件、改尺寸”的机械设计工程师、自动化工程师。

---

## 2. 当前已实现能力（v0.82）

- 支持 3 个模板零件族：
  - `motor_mount_bracket`（电机/减速机安装支架）
  - `flange_connector_plate`（法兰/连接板）
  - `sheet_metal_cover`（钣金外壳）
- 支持三种输入：
  - JSON 文件
  - Excel 表格
  - Web 表单
- 支持默认参数回填，用户没填时，会自动补默认值
- 支持参数边界校验与模板自定义校验，输入会自检合理性
- 支持本地 SolidWorks 执行（需要环境Windows + pywin32）
- 支持 Dry-run（不连 SW，用于流程联调）
- 支持输出命名版本化、日志记录、宏文件留档

---

## 3. 运行环境

### 必需

- Windows 10/11
- Python 3.11+
- SolidWorks（用于真实生成，本项目所用solidworks版本为2024 sp01）

### 安装 Python 依赖

见 [requirements.txt](requirements.txt)：

- `fastapi`
- `uvicorn`
- `pydantic`
- `openpyxl`
- `jinja2`
- `pywin32`（仅 Windows 真实 CAD）

---

## 4. 省事启动法

不想折腾直接从这里进。

双击根目录：

- [启动Web.bat](启动Web.bat)

该脚本会：

1. 检查 Python
2. 自动安装依赖（若缺失）
3. 启动 API 服务 `127.0.0.1:8000`
4. 自动打开浏览器
5. 启动脚本窗口自动退出

Web 页面入口：`http://127.0.0.1:8000`
失败可能是端口占用，改端口或清程序。

---

## 5. CLI 用法（工程调试）

### 5.1 安装依赖

```powershell
python -m pip install -r requirements.txt
```

### 5.2 Dry-run（不调用 SW）

```powershell
python -m app.main --input examples/default_motor.json --dry-run
```

### 5.3 真实 SolidWorks 生成

```powershell
python -m app.main --input examples/default_motor.json
```

### 5.4 Excel 输入

```powershell
python -m app.main --excel examples/motor_mount.xlsx
```

### 5.5 指定输出目录（例如桌面）

```powershell
$out = Join-Path ([Environment]::GetFolderPath('Desktop')) 'ParamCAD_Output'
python -m app.main --input examples/default_motor.json --output-dir $out
```

---

## 6. Web/API 接口

- `GET /`：Web 页面
- `GET /templates`：模板参数结构
- `POST /generate`：执行生成
- `GET /health`：健康检查

`POST /generate` 示例：

```json
{
  "template": "motor_mount_bracket",
  "length": 160,
  "width": 72,
  "height": 50,
  "plate_thickness": 6,
  "hole_diameter": 6,
  "hole_count": 4,
  "hole_spacing": 20,
  "fillet_radius": 3,
  "use_real_cad": true,
  "generate_drawing": false,
  "output_dir": "D:\\Users\\你\\Desktop\\ParamCAD_Output"
}
```

如果你已经有自己的上层系统，其实可以直接调这个接口，就不用走web。
---

## 7. 输出与命名规则

默认输出目录：`output/`

- 零件：`output/parts/*.SLDPRT`
- 工程图占位：`output/parts/*.SLDDRW`（当前为占位壳）
- 宏：`output/macros/*.swp`
- 日志：`output/logs/*.log.json`

命名示例：

- `motor_mount_bracket_L160_W72_H50_HD6_HC4_v1.SLDPRT`

版本号 `vN` 自动递增，避免覆盖历史结果。

---

## 8. 核心架构与数据流

```text
参数输入(JSON/Excel/Web)
  -> InputParser
  -> TemplateManager(模板定义)
  -> Validator(边界+约束)
  -> MacroGenerator(宏模板填充)
  -> CAD Executor
      - DryRunExecutor
      - SolidWorksExecutor
  -> OutputManager(命名/保存/日志)
```

关键目录：

- [app/core](app/core)：数据模型、模板管理、校验
- [app/services](app/services)：解析、宏生成、CAD执行、输出、流程编排
- [app/api](app/api)：FastAPI 接口
- [web/index.html](web/index.html)：中文 Web UI
- [static/template_registry.json](static/template_registry.json)：模板参数定义
- [static/template_bindings.json](static/template_bindings.json)：参数到 SW 尺寸句柄映射
- [static/model_templates](static/model_templates)：模板零件

如果后续要继续扩模板、补能力，基本也就是围绕这些目录往下长。

---

## 9. 模板参数清单（当前）

### 9.1 电机/减速机安装支架 `motor_mount_bracket`

核心参数：

- `length`, `width`, `height`
- `plate_thickness`
- `hole_diameter`, `hole_count`, `hole_spacing`
- `fillet_radius`（可选）

### 9.2 法兰/连接板 `flange_connector_plate`

核心参数：

- `outer_diameter`, `inner_diameter`
- `plate_thickness`
- `hole_count`, `hole_diameter`, `hole_spacing`
- `boss_height`

### 9.3 钣金外壳 `sheet_metal_cover`

核心参数：

- `length`, `width`, `height`
- `plate_thickness`, `bend_radius`
- `mounting_holes`
- `cutout_positions`

绑定关系详情见：

- [docs/template_parameter_plan_zh.md](docs/template_parameter_plan_zh.md)
- [static/template_bindings.json](static/template_bindings.json)

---

## 10. GitHub 上传前已处理内容

本仓库已按“可发布”方式整理：

- 新增 [.gitignore](.gitignore)
  - 忽略 `__pycache__`、`.venv`、IDE 缓存
  - 忽略 `output/**` 运行产物
  - 保留 `output/.gitkeep` 以维持目录结构
- 保留示例输入与静态模板，确保clone后可复现

建议你上传前执行：

```powershell
git status
```

确认没有把本地运行产物带入暂存区。

---

## ★11. 当前预想的后续版本新增功能/升级路线 

### 阶段 A：工程图自动化（从占位到真实图纸）

目标：勾选“生成工程图”后输出带视图/标题栏的 `.SLDDRW`。

实现步骤：

1. 在 `static/drawing_templates/` 放工程图模板（A3/A4、标题栏）。
2. 在 [app/services/cad_executor.py](app/services/cad_executor.py) 增加：
   - 新建 drawing 文档 / 设置用例调用固定图板
   - 插入主视图/俯视/侧视
   - 关联生成的 part
3. 在日志中写入 drawing 视图创建结果。

验收标准：

- 输出 `.SLDDRW` 可打开且包含至少 1 个模型视图。
- 模型改参后图纸可自动更新。

后续甚至可以导出DWG并优化SW导出逻辑，修复一定程度不兼容的尺寸标注和显示问题。

---

### 阶段 B：完善`custom_ops` 结构化自定义特征

目标：在同类型零件偶尔有额外与众不同的“小需求”时，支持用户在“自定义需求”里新增孔、圆角、切除等，不只改尺寸。
（如果是不同类型的更复杂零件 ，直接找个质量好点的模板模型，继续照葫芦画瓢增加参数映射逻辑就行。）
（ 详见 9 ）

推荐数据结构：

```json
{
  "template": "flange_connector_plate",
  "outer_diameter": 210,
  "custom_ops": [
    {"op": "add_hole", "diameter": 10, "x": 20, "y": 0, "depth": "through"},
    {"op": "edge_fillet", "radius": 2, "edge_selector": "outer"},
    {"op": "extrude_cut", "face": "top", "depth": 2, "direction": "reverse"}
  ]
}
```

实现步骤：

1. 在 [app/core/models.py](app/core/models.py) 增加 `CustomOp` 模型。
2. 在 [app/services/input_parser.py](app/services/input_parser.py) 解析并校验 `custom_ops`。
3. 在 [app/services/cad_executor.py](app/services/cad_executor.py) 新增 `_apply_custom_ops()`。
4. 每类模板先支持 2-3 个高频 op，逐步扩展。

验收标准：

- 同一模板支持“改参数 + 增特征”组合执行。
- 失败时日志能定位到第几个 `custom_op`。

---

### 阶段 C：备注文本/NLP 解析（自然语言入口——终极目标）

目标：把“备注”通过接入大模型api辅助分析转成 `custom_ops`，但求稳执行层仍只接受结构化指令；或者另开分支走另一条路线：直接写.swp宏（上限更高但不稳定）。
By the way：后续设计师自己常用模型也可以直接扔给大模型清洗处理。

实现步骤：

1. 增加 `nlp_parser` 模块：`remark text -> custom_ops`。
2. 输出“解析确认预览”给用户二次确认。
3. 通过后再进入 CAD 执行。

验收标准：

- 模糊语句不会直接执行，必须先结构化确认。
- 解析准确率和失败样例可追踪。

---

### 阶段 D：BOM/表格识别导入

目标：依旧大模型api通过识图 skill 从 BOM / 图纸 直接生成参数 JSON。

实现步骤：

1. 在 [app/services/input_parser.py](app/services/input_parser.py) 增加 BOM 模式识别。
2. 引入“字段映射表”：列名 -> 参数名。
3. 支持批量生成（一次多零件）。

验收标准：

- 常见 BOM 表头可自动识别。
- 批量任务失败项可单独重试。

---

### 阶段 E：模板版本化与云端 API（工程化）

目标：多人协作、模板版本管理、服务化调用。

实现步骤：

1. `template_registry.json` 增加版本字段与兼容策略。
2. 提供 `/v1/templates/{name}/versions` API。
3. 引入任务队列与作业状态查询。

那就是后话了，balabala又是一堆配置。当前项目结构很清晰，后续直接延展就可以。

---

## 12. 常见问题

### Q1：为什么会弹 SolidWorks 宏失败窗口？

默认已关闭宏执行，仅保留“参数写回 + rebuild + 保存”。若要尝试宏执行，修改环境变量：

```powershell
$env:PARAMCAD_ENABLE_SW_MACRO = "1"
```

### Q2：勾选“同时生成工程图占位文件”是什么意思？

当前仅创建 `.SLDDRW` 占位文件壳，方便文件管理需求。不自动插入视图（此为后续功能）。详见“阶段 A”。

### Q3：为什么有时报“零实体”？

这是安全保护：参数导致 rebuild 后实体数为 0 时会直接报错，避免产出无效零件。

---

## 13. 免责声明

- 本项目涉及本地 COM 调用 SolidWorks，受安装版本、权限、模板质量影响较大。
- 建议先在 Dry-run 验证参数与流程，再切换真实 CAD。
- 若是正式生产使用需要，使用前，需补齐回归用例与模板约束多次回测。

