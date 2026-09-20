# Voyager 1 × Ansys Workbench 仿真接口

本目录为 Voyager 1 科研助手提供的 **Ansys Workbench 仿真接口**：自动探测安装、以批处理模式运行 Journal 脚本（`.wbjn`），并附常用分析模板与教程。

```
ansys/
├── workbench.py              # 核心接口(探测 + 运行 + 模板)
├── __init__.py               # 包入口
├── examples/
│   ├── example_structural.wbjn  # 静力结构分析示例
│   └── example_modal.wbjn       # 模态分析示例
└── README.md                 # 本教程
```

---

## 1. 环境要求

- **Ansys Workbench**（2021R1 及以上；经典 Mechanical / MAPDL 均可，接口统一走 Workbench 批处理）
- Windows 10/11
- 未安装 Workbench 时探测函数返回 `None`，接口调用会给出明确提示，不影响应用其余功能。

## 2. 检测与配置

接口按以下顺序自动探测 `RunWB2.exe`：

1. 环境变量 `ANSYS_RUNWB2`（或 `ANSYS_WORKBENCH_RUNWB`）直接指定完整路径
2. 注册表 `HKLM\SOFTWARE\WOW6432Node\ANSYS Inc\ANSYS Install` 的 InstallLocation
3. 常见安装目录 `C:/D:/E: Program Files\ANSYS Inc\v*\Framework\bin\Win64\RunWB2.exe`

**设置环境变量（推荐，最可靠）**：

```bat
setx ANSYS_RUNWB2 "C:\Program Files\ANSYS Inc\v252\Framework\bin\Win64\RunWB2.exe"
```

设置后需重启终端/应用。也可以在代码里手动指定路径：

```python
from ansys.workbench import Workbench, find_workbench

print("探测结果:", find_workbench())          # 自动探测
wb = Workbench(runwb_path=r"C:\...\RunWB2.exe")  # 手动指定
print("可用:", wb.available)
```

## 3. 快速开始

### 3.1 运行现成示例

```python
from ansys.workbench import run_journal

result = run_journal(r"ansys\examples\example_structural.wbjn")
print(result["ok"], result["log"][-500:])
```

### 3.2 用模板生成脚本再运行

```python
from ansys.workbench import make_structural_journal, run_journal

script = make_structural_journal(
    project_path=r"ansys\output\my_plate.wbpj",
    geometry_file=r"D:\models\plate.step",   # 有几何文件就填
    force_load=1000,                          # 提示载荷(需在 Model 内选面)
)
result = run_journal(script, output_dir=r"ansys\output")
print(result)
```

### 3.3 参数说明

| 参数 | 说明 |
|---|---|
| `script_text` | Journal 内容字符串，或现有 `.wbjn` 文件路径 |
| `runwb_path` | RunWB2.exe 路径（None 自动探测） |
| `project_file` | 可选，打开已有项目 `.wbpj`（`-P`） |
| `output_dir` | 可选，工作目录（结果文件写这里） |
| `timeout` | 超时秒数，默认 1800（30 分钟） |

返回：`{"ok": bool, "log": str(尾部4000字符), "output_dir": str}`

## 4. Journal(.wbjn) 脚本要点

Workbench 的 Journal 是 **IronPython** 脚本，常见 API：

```python
project = NewProject()                        # 新建项目
project.SaveAs(r"D:\out\a.wbpj")              # 保存
template = GetTemplate(TemplateName="Static Structural")  # 系统模板名
system = template.CreateSystem()              # 创建分析系统
geom = system.GetContainer(ComponentName="Geometry")     # 获取组件
geom.SetFile(r"D:\models\plate.step")         # 指定几何文件
geom.Edit(Interactive=False)                  # 非交互刷新
model = system.GetContainer(ComponentName="Model")
model.Edit(Interactive=False)                 # 网格/边界条件
solution = system.GetContainer(ComponentName="Solution")
solution.Edit(Interactive=False)              # 求解
project.Save(); project.Close()
```

常用模板名：`Static Structural`、`Modal`、`Steady-State Thermal`、`Transient Structural`、`Fluid Flow (Fluent)`、`Harmonic Response` 等。

**重要**：
- `Interactive=False` 表示批处理不弹窗，适合自动化；调试时可改为 `True` 人工操作
- 载荷/约束需要在 Model 内按面、边、点施加，journal 里可通过 Mechanical 的录制脚本得到精确写法（Workbench 里操作一遍后 File → Write Journal 可导出）
- 第一次运行某版本 Workbench 会初始化，耗时较长，请耐心等待

## 5. 与 Voyager 1 配合使用

1. **让 Voyager 生成脚本**：在对话里描述分析需求（几何、材料、载荷、边界条件），要求它"给出 Ansys Workbench journal 脚本（.wbjn）"，它会按上面的 API 结构生成
2. **保存脚本**：把生成的脚本存为 `ansys\examples\my_case.wbjn`
3. **运行**：用本接口执行，或手动 `RunWB2.exe -B -R my_case.wbjn`
4. **结果回传**：把输出日志/结果路径粘贴回对话，让 Voyager 协助解读（应力云图数据、频率数值等）

> 提示：Voyager 的模型上下文里没有自动注入本接口，请把 `ansys\README.md` 的关键段落复制到对话里让它"学会"接口约定。

## 6. 常见问题

**Q: 返回"未检测到 Ansys Workbench"？**
A: 确认已安装 Workbench；或设置环境变量 `ANSYS_RUNWB2` 指向 RunWB2.exe 后重试；或 `Workbench(runwb_path=...)` 手动指定。

**Q: 运行后 `ok=False` 且日志为空/很短？**
A: 首次运行版本初始化、许可证检查可能较慢；增大 `timeout`；查看 Workbench 日志目录（`%TEMP%` 下 ansys 相关文件）。

**Q: 许可证错误？**
A: 接口不处理授权；请确认本机 Workbench 可用（能正常打开 GUI）再试批处理。

**Q: 可以并行跑多个仿真吗？**
A: 可以，但需不同输出目录；Workbench 批处理占用较大内存，建议串行。

**Q: 无几何文件怎么用？**
A: 模板会打开空 Geometry；可在 Workbench GUI 中手工建模后保存项目，再用 `project_file` 参数打开继续。
