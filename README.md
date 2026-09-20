# Voyager 1 · 深空科研助手

一个**桌面端科研辅助 AI Agent**，人设是 1977 年发射、如今已飞出日球层的旅行者一号（Voyager 1）。
它把「严谨的同行」当作回答标准：结论先行、分级标注、带来源，不确定就直说。

> 界面：PySide6 桌面应用 · 白 / 浅灰 + 蓝金配色 · 无边框卡片式布局
> 模型：DeepSeek API（`deepseek-chat`）· 支持流式输出与工具调用

---

## 功能

| 能力 | 说明 |
|---|---|
| **科研检索** | 内置多路检索：arXiv / PubMed / Nature / Science / Cell / NEJM / PNAS / OpenAlex / Crossref / Semantic Scholar / Wikipedia，回答自动用 `[1](链接)` 标注来源 |
| **分级表述** | 明确区分「已验证 / 有证据支持 / 尚属推测」，依据不足时回答「现有信息不足以判断」 |
| **分层记忆** | SQLite（WAL）持久化：会话消息 + 全局事实 + 学习笔记，支持查看、单条删除、清空；删除记忆时同步清理对话记录 |
| **沉思 / 好奇心** | 空闲时自主检索最近的科学进展并沉淀成笔记，形成「研发日志 / 学习笔记」 |
| **主动说话** | 长时间空闲后，会挑一个自己关心的话题主动开口（可在配置里关闭） |
| **屏幕感知** | 读取前台窗口（纯 `ctypes`，无额外依赖）与可选 OCR，让它在合适的时机知道你正在做什么 |
| **太阳系实时地图** | 对话页背景：按 JPL Horizons 实时数据绘制行星轨道与旅行者一号 / 二号位置及历史轨迹；右键拖拽绕垂直轴旋转（椭圆不变形），Ctrl + 滚轮缩放 |
| **Ansys 接口** | `ansys/` 目录提供 Workbench 批处理接口与 Journal 模板（默认关闭，见 `ansys/README.md`） |

---

## 快速开始

### 1. 环境

- Windows 10 / 11
- Python **3.12**（其余版本未测试）
- 一个 DeepSeek API Key（<https://platform.deepseek.com>）

### 2. 安装依赖

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

### 3. 配置

复制配置模板，填入你自己的 Key：

```bat
copy config.example.json config.json
```

```jsonc
{
  "deepseek_api_key": "sk-你的KEY",   // ← 必填
  "model": "deepseek-chat"
}
```

> `config.json` 已被 `.gitignore` 忽略，**不会**被提交。请勿把真实 Key 写进任何被跟踪的文件。

### 4. 启动

```bat
run.bat
```

或：

```bat
python main.py
```

首次启动会在项目根目录生成 `data/voyager.db`（记忆库）。

### 5. 打包成 exe（可选）

```bat
pip install pyinstaller
pyinstaller Voyager1.spec
```

产物在 `dist/Voyager1/Voyager1.exe`。

---

## 配置项速查

`config.json` 与 `app/config.py` 中的 `DEFAULTS` 深度合并，只需写要覆盖的字段。
主要开关：

| 键 | 默认 | 作用 |
|---|---|---|
| `deepseek_api_key` | `""` | DeepSeek API Key |
| `model` / `base_url` | `deepseek-chat` / `https://api.deepseek.com` | 模型与端点 |
| `search.enabled` | `true` | 是否允许联网检索 |
| `screen.enabled` | `true` | 屏幕感知（前台窗口 + OCR） |
| `situation.enabled` | `true` | 情景判断（结合感知推断你在做什么） |
| `rumination.enabled` | `true` | 空闲沉思 |
| `curiosity.enabled` | `true` | 好奇心驱动的自主检索 |
| `initiative.enabled` | `true` | 主动开口 |
| `ansys.enabled` | `false` | Ansys Workbench 接口 |
| `ui.bubble_opacity` | `0.9` | 对话气泡不透明度 |

> **隐私提示**：`screen` / `situation` 会读取前台窗口标题，OCR 开启后还会读取屏幕文字。
> 所有内容只写入本地 `data/voyager.db`，不会上传；不需要时请在设置页关闭。

---

## 目录结构

```
voyager-1/
├── main.py                  # 启动入口
├── config.example.json      # 配置模板（不含任何密钥）
├── requirements.txt
├── run.bat                  # 一键启动
├── Voyager1.spec            # PyInstaller 打包配置
├── app/
│   ├── config.py            # 配置加载 + 默认值
│   ├── llm.py               # DeepSeek 客户端（SSE 流式 + tool calling）
│   ├── core/
│   │   ├── persona.py       # 系统提示词
│   │   ├── agent.py         # 对话主循环、工具调用（检索 / 仿真）
│   │   ├── memory.py        # SQLite 分层记忆
│   │   ├── search.py        # 多源学术检索
│   │   ├── compact.py       # 上下文压缩
│   │   ├── rumination.py    # 沉思
│   │   ├── curiosity.py     # 好奇心
│   │   ├── initiative.py    # 主动说话
│   │   ├── screenwatch.py   # 前台窗口 + OCR
│   │   ├── situation.py     # 情景判断
│   │   ├── procs.py         # 进程观察
│   │   └── backdoor.py      # 口令验证（密钥由使用者在 config.json 自行设置）
│   └── ui/
│       ├── main_window.py   # 主窗口
│       ├── solar_map.py     # 太阳系实时地图
│       └── theme.py         # 配色与 QSS
└── ansys/                   # Ansys Workbench 接口（可选）
```

---

## 说明

- 运行时产生的 `data/`、`config.json`、`build/`、`dist/` 均已加入 `.gitignore`，**不纳入版本管理**。
- 仓库中**不包含**任何 API Key、访问口令或对话数据；`config.example.json` 中的密钥字段全部为空。
- 检索结果来自公开学术数据源，请遵守各站点的使用条款；模型输出请自行核实，尤其是数字与结论。
- 本项目仅供学习与研究使用，采用 [MIT License](LICENSE)。
