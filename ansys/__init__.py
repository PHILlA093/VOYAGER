"""Voyager 1 × Ansys Workbench 仿真接口。

用法见 README.md。
"""

from .workbench import (
    Workbench,
    find_workbench,
    make_modal_journal,
    make_structural_journal,
    run_journal,
)

__all__ = [
    "Workbench",
    "find_workbench",
    "make_modal_journal",
    "make_structural_journal",
    "run_journal",
]
