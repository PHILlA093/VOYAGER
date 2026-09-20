"""Voyager 1 × Ansys Workbench 仿真接口。

功能:
- find_workbench():自动探测 RunWB2.exe(环境变量 ANSYS_RUNWB2 / 注册表 / 常见路径)
- run_journal():以批处理模式(-B -R)运行 Workbench Journal 脚本(.wbjn)
- Workbench:便捷类封装
- make_structural_journal() / make_modal_journal():常用模板生成

注意:
- Workbench 是商业软件,本接口只做探测与调用,不包含任何破解或授权逻辑。
- 运行 journal 会真实驱动 Workbench 计算,请先确认脚本内容。
"""
import os
import subprocess
import tempfile
from pathlib import Path

__all__ = [
    "find_workbench",
    "run_journal",
    "Workbench",
    "make_structural_journal",
    "make_modal_journal",
]


def find_workbench():
    """探测 Ansys Workbench 可执行文件 RunWB2.exe 的完整路径。

    探测顺序:
    1. 环境变量 ANSYS_RUNWB2(或 ANSYS_WORKBENCH_RUNWB)直接指定
    2. 注册表 HKLM\\SOFTWARE\\WOW6432Node\\ANSYS Inc\\ANSYS Install 的 InstallLocation
    3. 常见安装目录(C:/D:/E: Program Files\\ANSYS Inc\\v*\\Framework\\bin\\Win64)
    返回绝对路径字符串;未找到返回 None。
    """
    env = os.environ.get("ANSYS_RUNWB2") or os.environ.get("ANSYS_WORKBENCH_RUNWB")
    if env and Path(env).exists():
        return str(Path(env))

    candidates = []
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\WOW6432Node\ANSYS Inc\ANSYS Install",
        )
        loc, _ = winreg.QueryValueEx(key, "InstallLocation")
        if loc:
            candidates.append(Path(loc))
    except Exception:
        pass

    for base in (
        r"C:\Program Files\ANSYS Inc",
        r"D:\Program Files\ANSYS Inc",
        r"E:\Program Files\ANSYS Inc",
    ):
        b = Path(base)
        if b.exists():
            candidates.extend(sorted(b.glob("v*")))

    seen = set()
    for cand in candidates:
        try:
            cand = cand.resolve() if cand.exists() else cand
        except Exception:
            continue
        if str(cand) in seen:
            continue
        seen.add(str(cand))
        p = cand / "Framework" / "bin" / "Win64" / "RunWB2.exe"
        if p.exists():
            return str(p)
    return None


def run_journal(script_text, runwb_path=None, project_file=None, output_dir=None, timeout=1800):
    """以批处理模式运行 Workbench Journal 脚本。

    参数:
        script_text: journal 脚本内容(字符串),或现有 .wbjn 文件的路径。
        runwb_path: RunWB2.exe 路径;None 时自动探测。
        project_file: 可选,要打开的项目 .wbpj 路径(-P)。
        output_dir: 可选,工作目录(结果文件将写在这里)。
        timeout: 秒,默认 1800(30 分钟)。

    返回:
        {"ok": bool, "log": str(尾部4000字符), "output_dir": str}
    """
    runwb = runwb_path or find_workbench()
    if not runwb:
        return {
            "ok": False,
            "log": (
                "未检测到 Ansys Workbench(RunWB2.exe)。\n"
                "请先安装 Ansys Workbench,或将 RunWB2.exe 路径写入环境变量 ANSYS_RUNWB2。"
            ),
            "output_dir": output_dir or "",
        }

    tmp = Path(tempfile.mkdtemp(prefix="voyager_ansys_"))
    src = Path(script_text)
    if src.exists():
        script = src
    else:
        script = tmp / "journal.wbjn"
        script.write_text(script_text, encoding="utf-8")

    cmd = [runwb, "-B", "-R", str(script)]
    if project_file:
        cmd += ["-P", str(project_file)]

    cwd = output_dir or str(tmp)
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd,
            encoding="utf-8", errors="replace",
        )
        log = (proc.stdout or "") + "\n" + (proc.stderr or "")
        return {
            "ok": proc.returncode == 0,
            "log": log[-4000:],
            "output_dir": cwd,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "log": f"仿真超时(超过 {timeout} 秒),已终止。", "output_dir": cwd}
    except Exception as e:
        return {"ok": False, "log": f"启动 Workbench 失败:{e}", "output_dir": cwd}


class Workbench:
    """Ansys Workbench 便捷客户端。"""

    def __init__(self, runwb_path=None):
        self.runwb = runwb_path or find_workbench()

    @property
    def available(self):
        return bool(self.runwb)

    @property
    def path(self):
        return self.runwb

    def run(self, script_text, **kwargs):
        return run_journal(script_text, runwb_path=self.runwb, **kwargs)


def make_structural_journal(project_path, geometry_file=None, force_load=None):
    """生成「静力结构分析」journal 模板。

    参数:
        project_path: 保存的项目 .wbpj 完整路径。
        geometry_file: 可选,几何文件路径(.scdoc/.step/.stp/.x_t 等);
                      为空时只创建系统骨架,需要手工建模。
        force_load: 可选,施加的力(N),写入模板注释供参考。
    """
    lines = [
        "# -*- coding: utf-8 -*-",
        '# 静力结构分析模板:带孔板/自定义几何 -> 网格 -> 求解等效应力',
        'import os',
        '',
        f'project_path = r"{project_path}"',
        'project = NewProject()',
        'project.SaveAs(project_path)',
        '',
        'template = GetTemplate(TemplateName="Static Structural")',
        'system = template.CreateSystem()',
        '',
    ]
    if geometry_file:
        lines += [
            f'geometry_file = r"{geometry_file}"',
            'geom_comp = system.GetContainer(ComponentName="Geometry")',
            'geom_comp.SetFile(geometry_file)',
            'geom_comp.Edit(Interactive=False)',
            '',
        ]
    else:
        lines += [
            '# 无几何文件:请打开 Geometry 手工建模,或填入 geometry_file 参数',
            'geom_comp = system.GetContainer(ComponentName="Geometry")',
            'geom_comp.Edit(Interactive=False)',
            '',
        ]
    if force_load:
        lines += [
            f'# 施加力(N):{force_load}(请在 Model 内按面/边选择施力位置)',
        ]
    lines += [
        'model = system.GetContainer(ComponentName="Model")',
        'model.Edit(Interactive=False)',
        '',
        'solution = system.GetContainer(ComponentName="Solution")',
        'solution.Edit(Interactive=False)',
        '',
        'project.Save()',
        'project.Close()',
    ]
    return "\n".join(lines)


def make_modal_journal(project_path, geometry_file=None):
    """生成「模态分析」journal 模板(前 N 阶固有频率与振型)。"""
    lines = [
        "# -*- coding: utf-8 -*-",
        "# 模态分析模板:提取前 6 阶固有频率与振型",
        'import os',
        '',
        f'project_path = r"{project_path}"',
        'project = NewProject()',
        'project.SaveAs(project_path)',
        '',
        'template = GetTemplate(TemplateName="Modal")',
        'system = template.CreateSystem()',
        '',
    ]
    if geometry_file:
        lines += [
            f'geometry_file = r"{geometry_file}"',
            'geom_comp = system.GetContainer(ComponentName="Geometry")',
            'geom_comp.SetFile(geometry_file)',
            'geom_comp.Edit(Interactive=False)',
            '',
        ]
    else:
        lines += [
            'geom_comp = system.GetContainer(ComponentName="Geometry")',
            'geom_comp.Edit(Interactive=False)',
            '',
        ]
    lines += [
        'model = system.GetContainer(ComponentName="Model")',
        'model.Edit(Interactive=False)',
        '',
        'solution = system.GetContainer(ComponentName="Solution")',
        '# 可在此设置求解的模态阶数(默认 6 阶)',
        'solution.Edit(Interactive=False)',
        '',
        'project.Save()',
        'project.Close()',
    ]
    return "\n".join(lines)
