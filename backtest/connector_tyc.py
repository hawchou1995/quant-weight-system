#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""connector_tyc.py —— 天眼查 tyc-mcp 企业数据接口 · 可复用调用脚本

端点：https://mcp.tianyancha.com/v1   （streamableHTTP MCP，JSON 响应）
鉴权：请求头 `Authorization: Bearer <token>`（key 见 connector-keys.json → tianyancha.key）

★ 2026-09-16 实测结论（重要）：用户提供的 uuid 是**天眼查开放平台 raw OpenAPI token**，
  能在本 MCP 端点完成 initialize / tools/list（HTTP 200，返回 17 个工具），
  但任何 tools/call 均被拒：
    {"error":"invalid_token","error_description":"raw OpenAPI tokens are not accepted; use OAuth or an MCP API key"}
  同时开放平台老网关 https://open.api.tianyancha.com/services/... 对该 token 返回
    {"error_code":300005,"reason":"无权限访问此api"}   （= token 有效但未开通接口权限）
  → 要真正取数需二选一：① 到 https://ai.tianyancha.com 申请 **MCP API key**（或走 OAuth 连接器）；
     ② 到 https://open.tianyancha.com 为现有 token 申请/购买接口权限（300005 才会消失）。

工具：聚合式网关。公开入口 search_companies / get_company_basic_profile /
      get_company_group_profile / get_group_info / get_company_people / get_person_profile /
      get_person_risk_profile / get_company_capabilities / call_tool / call_tools_batch /
      search_companies_by_industry_region / search_companies_by_tag / search_companies_by_ranking /
      search_listed_companies / search_bids / search_patents / search_trademarks
工作流：先用 search_companies 锚定（拿 企业ID/精确名称）→ 再用 get_company_capabilities
        取该公司真实 tool_name → call_tool 调用
规范：限速 >=0.3s、重试 <=2、结果落 D:/Tools/cache/connectors/tyc/

用法：
    python connector_tyc.py tools
    python connector_tyc.py search "贵州茅台"
    python connector_tyc.py call search_companies '{"keyword":"贵州茅台"}'
    python connector_tyc.py call get_company_basic_profile '{"company_name":"贵州茅台酒股份有限公司"}'
"""
import json
import sys

sys.path.insert(0, "D:/Documents/Workbuddy/股票基金/quant-weight-system/backtest")
from connector_mcp import build_client, save_json  # noqa: E402

NAME = "tyc"


def _client():
    return build_client(NAME, timeout=120)


def list_tools():
    c = _client()
    c.initialize()
    tl = c.list_tools()
    save_json(NAME, "tools", tl)
    return tl["names"]


def call(tool: str, args: dict):
    c = _client()
    c.initialize()
    r = c.call_tool(tool, args)
    save_json(NAME, f"call_{tool}", r)
    return r


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    if sys.argv[1] == "tools":
        print(json.dumps(list_tools(), ensure_ascii=False, indent=1))
    elif sys.argv[1] == "search":
        out = call("search_companies", {"keyword": sys.argv[2]})
        print(out["text"][:3000] or f"[FAIL] error={out['error']} raw={out['raw'][:400]}")
    elif sys.argv[1] == "call":
        out = call(sys.argv[2], json.loads(sys.argv[3]) if len(sys.argv) > 3 else {})
        print(json.dumps({"ok": out["ok"], "isError": out["isError"], "error": out["error"]}, ensure_ascii=False))
        print(out["text"][:4000])
    else:
        print(__doc__)
