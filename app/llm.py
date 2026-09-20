"""DeepSeek API 客户端(OpenAI 兼容协议,支持流式与工具调用)。"""
import json

import requests

from .core.net import request as net_request


class LLMError(Exception):
    pass


class DeepSeekClient:
    def __init__(self, config):
        self.config = config

    @property
    def _key(self):
        return self.config.get("deepseek_api_key", default="") or ""

    def _headers(self):
        if not self._key:
            raise LLMError("还没有配置 DeepSeek API Key,请在左侧「设置」页填写。")
        return {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }

    def _url(self):
        base = self.config.get("base_url", default="https://api.deepseek.com").rstrip("/")
        return base + "/chat/completions"

    def _payload(self, messages, tools=None, stream=False, max_tokens=None, temperature=None):
        payload = {
            "model": self.config.get("model", default="deepseek-chat"),
            "messages": messages,
            "stream": stream,
            "temperature": (
                temperature
                if temperature is not None
                else self.config.get("temperature", default=1.1)
            ),
            "max_tokens": (
                max_tokens
                if max_tokens is not None
                else self.config.get("max_tokens", default=2048)
            ),
        }
        if tools:
            payload["tools"] = tools
        return payload

    def _post(self, payload, timeout=90):
        try:
            resp = net_request(
                "post",
                self._url(),
                headers=self._headers(),
                json=payload,
                stream=payload.get("stream"),
                timeout=timeout,
            )
        except requests.RequestException as e:
            raise LLMError(f"网络请求失败:{e}") from e
        if resp.status_code != 200:
            try:
                detail = resp.json().get("error", {}).get("message", resp.text[:300])
            except Exception:
                detail = resp.text[:300]
            raise LLMError(f"API 返回 {resp.status_code}:{detail}")
        return resp

    def complete(self, messages, tools=None, max_tokens=None, temperature=None, timeout=90):
        """非流式调用,返回 message 字典 {content, tool_calls}。"""
        resp = self._post(
            self._payload(
                messages,
                tools=tools,
                stream=False,
                max_tokens=max_tokens,
                temperature=temperature,
            ),
            timeout=timeout,
        )
        data = resp.json()
        try:
            msg = data["choices"][0]["message"]
        except (KeyError, IndexError) as e:
            raise LLMError("API 响应格式异常") from e
        return {
            "content": msg.get("content") or "",
            "tool_calls": msg.get("tool_calls") or [],
        }

    def stream(self, messages, tools=None, max_tokens=None, temperature=None, timeout=120):
        """流式调用,生成器事件:
        ('text', 增量文本) | ('tool_calls', [tool_call]) | ('done', message字典)
        """
        resp = self._post(
            self._payload(
                messages,
                tools=tools,
                stream=True,
                max_tokens=max_tokens,
                temperature=temperature,
            ),
            timeout=timeout,
        )
        content_parts = []
        tool_calls = {}  # index -> {"id","name","arguments"}
        try:
            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    obj = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                choices = obj.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                if delta.get("content"):
                    chunk = delta["content"]
                    content_parts.append(chunk)
                    yield ("text", chunk)
                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    entry = tool_calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    if tc.get("id"):
                        entry["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        entry["name"] += fn["name"]
                    if fn.get("arguments"):
                        entry["arguments"] += fn["arguments"]
        finally:
            resp.close()
        msg = {"content": "".join(content_parts), "tool_calls": []}
        if tool_calls:
            calls = []
            for idx in sorted(tool_calls):
                e = tool_calls[idx]
                calls.append(
                    {
                        "id": e["id"],
                        "type": "function",
                        "function": {"name": e["name"], "arguments": e["arguments"]},
                    }
                )
            msg["tool_calls"] = calls
        yield ("done", msg)
