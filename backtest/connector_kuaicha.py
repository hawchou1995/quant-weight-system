#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""connector_kuaicha.py —— 同花顺快查（kuaicha）企业数据接口 · 可复用调用脚本

端点：https://bizveris.kuaicha365.com/mcp?source=workbuddy   （streamableHTTP MCP）
鉴权：请求头 `open-authorization: Bearer <JWE key>`（key 见 connector-keys.json → kuaicha.key）
工具：仅 2 个入口 —— `discover`(中文能力描述→tool_id 列表) / `call`(tool_id + params_to_tool)
规范：限速 >=0.3s、重试 <=2、结果落 D:/Tools/cache/connectors/kuaicha/

用法：
    python connector_kuaicha.py discover "企业股东信息"
    python connector_kuaicha.py call basic_get_enterprise_basic_info '{"corp_name":"贵州茅台酒股份有限公司"}'
    python connector_kuaicha.py q '{"corp_name":"贵州茅台酒股份有限公司"}'   # 一步式 discover+call
"""
import json
import sys

sys.path.insert(0, "D:/Documents/Workbuddy/股票基金/quant-weight-system/backtest")
from connector_mcp import build_client, save_json  # noqa: E402

NAME = "kuaicha"


def _client():
    return build_client(NAME, timeout=60)


def discover(query: str, limit: int = 10):
    c = _client()
    c.initialize()
    r = c.call_tool("discover", {"query": query, "limit": limit})
    save_json(NAME, "discover", r)
    try:
        tools = json.loads(r["text"]).get("tools", [])
        return [{"tool_id": t.get("tool_id"), "name": t.get("name"),
                 "similarity": t.get("similarity"),
                 "params": [p.get("name") for p in (t.get("params") or [])]} for t in tools]
    except Exception:
        return r


def call(tool_id: str, params: dict):
    c = _client()
    c.initialize()
    r = c.call_tool("call", {"tool_id": tool_id, "params_to_tool": json.dumps(params, ensure_ascii=False)})
    save_json(NAME, f"call_{tool_id}", r)
    return r


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "discover":
        print(json.dumps(discover(sys.argv[2]), ensure_ascii=False, indent=1))
    elif cmd == "call":
        out = call(sys.argv[2], json.loads(sys.argv[3]) if len(sys.argv) > 3 else {})
        print(out["text"][:3000])
    elif cmd == "q":  # 一步式：先 discover 再 call（参数为 call 的 params）
        params = json.loads(sys.argv[2])
        found = discover("企业基本信息查询", limit=3)
        tid = found[0]["tool_id"] if found and isinstance(found, list) else None
        print("tool_id =", tid)
        out = call(tid, params)
        print(out["text"][:3000])
    else:
        print(__doc__)
