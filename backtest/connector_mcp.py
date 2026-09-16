#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""connector_mcp.py —— 新接口吸收（2026-09-16）通用 MCP streamable-HTTP 客户端

给 connector_kuaicha.py / connector_qcc.py / connector_tyc.py / connector_tongzhou.py 共用。

约束：
- 只读调用（不写第三方系统）
- 限速 >= 0.3s / 次
- 重试 <= 2 次
- 结果落盘 D:/Tools/cache/connectors/<name>/
- key 一律从 D:/Documents/Obsidian/personal/connector-keys.json 读取，绝不明文写进日志/报告

用法（python 3.8+，依赖 requests）：
    from connector_mcp import MCPClient, masked
    c = MCPClient(url, headers={"Authorization": "Bearer xxx"}, name="tyc")
    tools = c.list_tools()
    res = c.call_tool("search_companies", {"keyword": "贵州茅台"})
"""
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

KEYS_FILE = "D:/Documents/Obsidian/personal/connector-keys.json"
CACHE_ROOT = "D:/Tools/cache/connectors"
MCP_PROTOCOL_VERSION = "2025-06-18"

# 端点定义：来源为 WorkBuddy 连接器 mcp.json（connectors-marketplace / connectors 目录），非臆造
ENDPOINTS = {
    "kuaicha": {
        "url": "https://bizveris.kuaicha365.com/mcp?source=workbuddy",
        "auth_hdr": "open-authorization",     # marketplace mcp.json: open-authorization: Bearer ${KUAICHA_API_KEY}
        "auth_fmt": "Bearer {key}",
        "key_field": "kuaicha",
    },
    "qcc": {
        "url": "https://agent.qcc.com/mcp/company/stream",
        "auth_hdr": "Authorization",           # 实测：Bearer <token>
        "auth_fmt": "Bearer {key}",
        "key_field": "qcc_qichacha",
    },
    "tyc": {
        "url": "https://mcp.tianyancha.com/v1",
        "auth_hdr": "Authorization",           # 实测：Bearer <uuid token>
        "auth_fmt": "Bearer {key}",
        "key_field": "tianyancha",
    },
    "tongzhou": {
        "url": "https://mcp-gateway.textmind-gz.com/mcp/tongzhou-research",
        "auth_hdr": None,                      # OAuth 专用，无静态 key
        "auth_fmt": None,
        "key_field": None,
    },
}


def load_key(field: str) -> Optional[str]:
    """从 connector-keys.json 读取 key；找不到返回 None"""
    try:
        with open(KEYS_FILE, encoding="utf-8") as f:
            return (json.load(f).get(field) or {}).get("key")
    except Exception:
        return None


def masked(s: Optional[str], keep: int = 6) -> str:
    """打码：只保留前后少量字符"""
    if not s:
        return "<none>"
    if len(s) <= keep * 2:
        return s[:2] + "***"
    return s[:keep] + "***" + s[-4:]


def _cache_dir(name: str) -> str:
    d = os.path.join(CACHE_ROOT, name)
    os.makedirs(d, exist_ok=True)
    return d


def save_json(name: str, tag: str, payload: Any) -> str:
    """落盘 D:/Tools/cache/connectors/<name>/<tag>_<ts>.json"""
    d = _cache_dir(name)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(d, f"{tag}_{ts}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    return path


def _parse_body(text: str, content_type: str) -> Dict[str, Any]:
    """兼容 JSON 与 SSE(text/event-stream) 两种响应体"""
    text = (text or "").strip()
    if not text:
        return {}
    if "text/event-stream" in (content_type or "") or text.startswith("event:") or "\ndata:" in text or text.startswith("data:"):
        out: Dict[str, Any] = {}
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                raw = line[5:].strip()
                try:
                    out = json.loads(raw)
                except Exception:
                    pass
        return out
    try:
        return json.loads(text)
    except Exception:
        return {"_raw": text[:2000]}


class MCPClient:
    """极简 MCP streamable-HTTP 客户端（initialize → initialized → tools/list / tools/call）"""

    def __init__(self, url: str, headers: Optional[Dict[str, str]] = None,
                 name: str = "mcp", timeout: int = 60, min_interval: float = 0.35):
        self.url = url
        self.name = name
        self.timeout = timeout
        self.min_interval = min_interval      # 限速 >= 0.3s
        self.session_id: Optional[str] = None
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **(headers or {}),
        }
        self._last = 0.0
        self.log: List[Dict[str, Any]] = []

    # ---------- 底层 ----------
    def _throttle(self):
        wait = self.min_interval - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()

    def _post(self, payload: Dict[str, Any], retries: int = 2) -> Dict[str, Any]:
        """POST JSON-RPC，返回 {'ok','status','json','text','error'}；重试 <= 2"""
        hdrs = dict(self.headers)
        if self.session_id:
            hdrs["Mcp-Session-Id"] = self.session_id
        last_err = None
        for attempt in range(retries + 1):
            self._throttle()
            try:
                r = requests.post(self.url, headers=hdrs, json=payload,
                                  timeout=self.timeout)
                sid = r.headers.get("Mcp-Session-Id") or r.headers.get("mcp-session-id")
                if sid:
                    self.session_id = sid
                # SSE/JSON 响应统一按 UTF-8 解码（否则中文会乱码）
                ctype = r.headers.get("Content-Type", "")
                if "text/event-stream" in ctype or "charset" not in ctype.lower():
                    try:
                        text = r.content.decode("utf-8", errors="replace")
                    except Exception:  # noqa: BLE001
                        text = r.text
                else:
                    text = r.text
                body = _parse_body(text, ctype)
                rec = {"status": r.status_code, "method": payload.get("method"),
                       "attempt": attempt, "session": bool(self.session_id)}
                self.log.append(rec)
                if r.status_code < 400:
                    return {"ok": True, "status": r.status_code, "json": body,
                            "text": text[:4000], "headers": dict(r.headers)}
                last_err = {"ok": False, "status": r.status_code, "json": body,
                            "text": text[:2000], "headers": dict(r.headers)}
            except Exception as e:  # noqa: BLE001
                last_err = {"ok": False, "status": -1, "json": {},
                            "text": f"{type(e).__name__}: {e}", "headers": {}}
            if attempt < retries:
                time.sleep(0.6 * (attempt + 1))
        return last_err or {"ok": False, "status": -1, "json": {}, "text": "unknown"}

    def _notify(self, method: str, params: Optional[Dict] = None):
        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        self._post(payload, retries=0)

    # ---------- 高层 ----------
    def initialize(self) -> Dict[str, Any]:
        payload = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"protocolVersion": MCP_PROTOCOL_VERSION,
                              "capabilities": {},
                              "clientInfo": {"name": "quant-weight-system", "version": "1.0"}}}
        res = self._post(payload)
        if not res.get("ok"):
            # 协议版本被拒时自动降级重试一次
            err = (res.get("json") or {}).get("error")
            sup = (err.get("data") or {}).get("supported") if isinstance(err, dict) else None
            if isinstance(sup, list) and sup:
                payload["params"]["protocolVersion"] = sup[0]
                res = self._post(payload)
        if res.get("ok"):
            self._notify("notifications/initialized")
        return res

    def rpc(self, method: str, params: Optional[Dict] = None, rid: Optional[int] = None) -> Dict[str, Any]:
        payload = {"jsonrpc": "2.0", "id": rid or int(time.time() * 1000) % 1_000_000,
                   "method": method}
        if params is not None:
            payload["params"] = params
        return self._post(payload)

    def list_tools(self) -> Dict[str, Any]:
        res = self.rpc("tools/list", {})
        tools = (((res.get("json") or {}).get("result") or {}).get("tools")) or []
        return {"ok": res.get("ok"), "status": res.get("status"), "tools": tools,
                "names": [t.get("name") for t in tools], "raw": res.get("text", "")[:1500]}

    def call_tool(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        res = self.rpc("tools/call", {"name": tool_name, "arguments": arguments or {}})
        j = res.get("json") or {}
        result = j.get("result") or {}
        content = result.get("content") or []
        texts = [c.get("text", "") for c in content if isinstance(c, dict)]
        return {"ok": res.get("ok") and not j.get("error"), "status": res.get("status"),
                "isError": bool(result.get("isError")),
                "error": j.get("error"),
                "text": "\n".join(texts)[:6000],
                "structured": result.get("structuredContent"),
                "raw": res.get("text", "")[:2000]}


def build_client(name: str, timeout: int = 60) -> MCPClient:
    """按 name 构造已带鉴权的客户端（key 来自 connector-keys.json）"""
    spec = ENDPOINTS[name]
    headers = {}
    if spec.get("auth_hdr"):
        key = load_key(spec["key_field"])
        if not key:
            raise SystemExit(f"[ERROR] connector-keys.json 缺少 {spec['key_field']}.key")
        headers[spec["auth_hdr"]] = spec["auth_fmt"].format(key=key)
    return MCPClient(spec["url"], headers=headers, name=name, timeout=timeout)
