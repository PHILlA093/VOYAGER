"""对话编排:人设注入 + 历史记忆 + 工具调用(科研网页搜索)+ 关键操作确认。

逻辑链:
1. 暗号校验 -> 2. 组装上下文(系统+历史+当前) -> 3. 请求模型(可带工具)
4. 无工具调用 -> 校验输出非空(空则自动纠正重试)
5. 有工具调用 -> 征得确认 -> 执行搜索(失败自动降级重试) -> 回填结果 -> 回到 3
6. 偏好学习 -> 记忆落库 -> 滚动整理
"""
import json
import re

from . import search as search_mod
from .persona import build_system_prompt
from .situation import situation_block

SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "搜索互联网获取实时信息(优先学术来源:arXiv/PubMed/Nature/Science 等)。"
            "当开拓者问到最新论文、研究进展、数据、新闻或你不确定的最新资讯时使用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "简洁的搜索关键词,中文或英文均可",
                }
            },
            "required": ["query"],
        },
    },
}

MAX_TOOL_ROUNDS = 3
EMPTY_RETRY_PROMPT = "(你刚才没有输出任何内容。请直接给出简洁的回答,不要使用工具。)"

ANSYS_TOOL = {
    "type": "function",
    "function": {
        "name": "run_ansys_simulation",
        "description": (
            "运行 Ansys Workbench 仿真(静力/模态/热等有限元分析)。"
            "你必须提供完整的 Workbench Journal 脚本内容(参数 script, IronPython 语法,"
            "包含 NewProject/GetTemplate/CreateSystem/GetContainer/Edit 等调用),"
            "接口会以批处理模式执行并返回日志。执行前需要开拓者确认。"
            "仅在开拓者明确要求做有限元仿真/应力分析/模态分析等时使用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "script": {
                    "type": "string",
                    "description": "完整的 Workbench Journal 脚本(IronPython;可参考模板:NewProject 创建、GetTemplate(TemplateName='Static Structural'/'Modal')、CreateSystem、GetContainer(ComponentName='Geometry'/'Model'/'Solution')、Edit(Interactive=False)、SaveAs、Close)",
                },
                "project_file": {
                    "type": "string",
                    "description": "可选,要打开的项目 .wbpj 路径;新建项目时留空",
                },
            },
            "required": ["script"],
        },
    },
}


class Agent:
    def __init__(self, config, memory, llm, searcher, backdoor=None):
        self.config = config
        self.memory = memory
        self.llm = llm
        self.searcher = searcher
        self.backdoor = backdoor

    def _system_prompt(self):
        unlocked = bool(self.backdoor and self.backdoor.unlocked)
        return build_system_prompt(
            memory=self.memory,
            situation_text=situation_block(self.memory, self.config),
            unlocked=unlocked,
        )

    # ---------- 请求封装 ----------

    def _request(self, messages, tools, on_token):
        """向模型请求一轮,返回 (tool_calls, collected_texts)。"""
        tool_calls = []
        collected = []
        for event in self.llm.stream(messages, tools=tools or None):
            kind = event[0]
            if kind == "text":
                collected.append(event[1])
                if on_token:
                    on_token(event[1])
            elif kind == "tool_calls":
                tool_calls = event[1]
            elif kind == "done":
                if not tool_calls:
                    tool_calls = event[1].get("tool_calls") or []
        return tool_calls, collected

    @staticmethod
    def _simplify_query(query):
        """检索降级用:去掉标点/引号,压缩为前 12 个字符的简单关键词。"""
        q = re.sub(r"[「」\"'()（）:：,，。.;；]+", " ", query or "")
        q = re.sub(r"\s+", " ", q).strip()
        if len(q) > 12:
            q = q[:12]
        return q

    def _execute_search(self, query, messages, tc, on_status):
        """执行一次搜索并回填工具结果;失败时自动降级重试一次。"""
        if on_status:
            on_status(f"正在检索「{query}」…")
        results = self.searcher.search(query)
        if results is None:
            # 降级:网络抖动或关键词过复杂时,用简化关键词再试一次
            fallback = self._simplify_query(query)
            if on_status:
                on_status(f"首次检索受阻,改用简化关键词重试…")
            results = self.searcher.search(fallback) if fallback != query else None
        if results is None:
            result = "检索失败(网络或服务暂时不可用),请如实告诉开拓者。"
        else:
            self.memory.log_search(query, results[0]["url"], accepted=True)
            result = "搜索结果:\n" + search_mod.format_results(results)
        messages.append(
            {"role": "tool", "tool_call_id": tc.get("id") or "", "content": result}
        )

    def _execute_ansys(self, args, messages, tc, on_status, on_search_confirm):
        """执行 Ansys Workbench 仿真工具调用(先征得开拓者确认)。"""
        script = str(args.get("script") or "").strip()
        project_file = str(args.get("project_file") or "").strip() or None
        if not script:
            result = "工具参数无效:缺少 script 内容,请生成完整的 Workbench Journal 脚本(IronPython)。"
        elif on_search_confirm is not None and not on_search_confirm(
            f"运行 Ansys Workbench 仿真(脚本 {len(script)} 字符)?"
        ):
            result = "开拓者拒绝了这次仿真。请尊重选择,不要执行;改为说明仿真方案或改进脚本。"
        else:
            if on_status:
                on_status("正在启动 Ansys Workbench 仿真…(批处理模式,可能耗时较长)")
            try:
                from ansys.workbench import run_journal

                acfg = self.config.get("ansys", default={}) or {}
                out = run_journal(
                    script,
                    runwb_path=acfg.get("runwb_path", "") or None,
                    project_file=project_file,
                    timeout=int(acfg.get("timeout", 1800)),
                )
                result = f"Ansys 仿真执行{'成功' if out['ok'] else '失败'}:\n{out['log'][-3000:]}"
                if out["ok"]:
                    result += f"\n输出目录:{out['output_dir']}"
            except Exception as e:
                result = f"仿真执行出错:{e!r}"
        messages.append(
            {"role": "tool", "tool_call_id": tc.get("id") or "", "content": result}
        )

    def run_turn(self, user_text, on_token=None, on_search_confirm=None, on_status=None, auto_compact=True):
        """执行一轮对话(自动处理暗号验证与工具调用),返回最终回复文本。"""
        if self.backdoor:
            self.backdoor.evaluate(user_text)

        system = self._system_prompt()
        history = self.memory.recent_messages(
            self.config.get("memory", "recent_messages", default=30)
        )
        messages = (
            [{"role": "system", "content": system}]
            + history
            + [{"role": "user", "content": user_text}]
        )

        search_enabled = bool(self.config.get("search", "enabled", default=True))
        ansys_enabled = bool(self.config.get("ansys", "enabled", default=True))
        tools = []
        if search_enabled:
            tools.append(SEARCH_TOOL)
        if ansys_enabled:
            tools.append(ANSYS_TOOL)
        final_text = ""

        for round_i in range(MAX_TOOL_ROUNDS):
            tool_calls, collected = self._request(messages, tools, on_token)

            if not tool_calls:
                final_text = "".join(collected)
                if final_text.strip():
                    break
                # 空输出:追加纠正提示重试一次(仅首轮)
                if round_i == 0:
                    if on_status:
                        on_status("模型无输出,正在纠正重试…")
                    messages.append({"role": "user", "content": EMPTY_RETRY_PROMPT})
                    continue
                final_text = "(未能生成回答,请重试或换一种问法。)"
                break

            # 工具调用轮:先征得开拓者同意再执行搜索
            messages.append(
                {"role": "assistant", "content": None, "tool_calls": tool_calls}
            )
            for tc in tool_calls:
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                name = (tc.get("function") or {}).get("name") or ""
                if name == "run_ansys_simulation":
                    self._execute_ansys(args, messages, tc, on_status, on_search_confirm)
                    continue
                query = str(args.get("query") or "").strip()
                if not query:
                    result = "工具参数无效:缺少 query,请直接回答开拓者。"
                    messages.append(
                        {"role": "tool", "tool_call_id": tc.get("id") or "", "content": result}
                    )
                elif on_search_confirm is not None and not on_search_confirm(query):
                    result = (
                        "开拓者拒绝了这次搜索。请尊重选择:要么直接回答,"
                        "要么说明你打算搜索什么并征得同意。"
                    )
                    self.memory.log_search(query, "", accepted=False)
                    messages.append(
                        {"role": "tool", "tool_call_id": tc.get("id") or "", "content": result}
                    )
                else:
                    self._execute_search(query, messages, tc, on_status)
        else:
            raise RuntimeError("工具调用轮次过多,已停止。")

        # 偏好学习:把常接受的来源域名写回配置
        try:
            domains = self.memory.accepted_domains(min_count=2)
            if domains:
                self.config.set(domains[:5], "search", "preferred_domains")
        except Exception:
            pass

        self.memory.add_message("user", user_text)
        self.memory.add_message("assistant", final_text)

        # 后台滚动整理较早的对话,防止细节丢失
        if auto_compact:
            try:
                from .compact import maybe_compact

                maybe_compact(self.config, self.memory, self.llm)
            except Exception:
                pass

        return final_text
