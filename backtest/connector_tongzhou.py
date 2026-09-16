#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""connector_tongzhou.py —— 同舟金融研究 MCP · 调用脚本（当前待授权）

端点：https://mcp-gateway.textmind-gz.com/mcp/tongzhou-research   （streamableHTTP MCP）
      来源：WorkBuddy connectors/mcp.json（connector:tongzhou-fin-research）
鉴权：MCP 原生 OAuth（或服务端"legacy API key"）。用户提供的 connector-keys.json 中
      tongzhou_fin_research.key = null，故当前实测 401：
      {"code":-32001,"message":"Unauthorized: connect the Tongzhou research account or provide a valid legacy API key",
       "data":{"portal_url":"https://mcp-gateway.textmind-gz.com/login"}}
      需要用户在 https://mcp-gateway.textmind-gz.com/login 完成登录，或在 WorkBuddy 重新连接
      「同舟金融研究」连接器后，本脚本方可复用（拿到 token 后放进 headers 即可）。

授权后工具前缀（见官方 SKILL.md）：
  fin_data__   search_security / get_latest_snapshot / batch_get_latest_snapshots /
               get_kline_series / batch_query_data / rank_etf_candidates /
               compute_market_reaction_windows / query_financial_indicators / query_sector_valuation
  doc_search__ search_hot_news / search_company_news / search_announcements /
               search_research_reports / get_document
  fin_graph__  resolve_research_identity / get_industry_chain_research_map /
               get_public_factor_framework / get_factor_evidence_panel / get_factor_metric_values
  same_boat__  search_research_sectors / list_market_news / list_sector_viewpoints

用法（授权后）：
    set TONGZHOU_TOKEN=xxx   （或改本文件 TOKEN_ENV 指向的变量）
    python connector_tongzhou.py ping
    python connector_tongzhou.py call fin_data__get_latest_snapshot '{"ticker":"600519.SH","market":"a_stock"}'
"""
import json
import os
import sys

sys.path.insert(0, "D:/Documents/Workbuddy/股票基金/quant-weight-system/backtest")
from connector_mcp import MCPClient, ENDPOINTS, save_json  # noqa: E402

NAME = "tongzhou"
TOKEN_ENV = "TONGZHOU_TOKEN"   # 授权后把 OAuth access token 放这里即可跑


def _client():
    headers = {}
    tok = os.environ.get(TOKEN_ENV)
    if tok:
        headers["Authorization"] = tok if tok.lower().startswith("bearer ") else f"Bearer {tok}"
    return MCPClient(ENDPOINTS[NAME]["url"], headers=headers, name=NAME, timeout=60)


def ping() -> dict:
    c = _client()
    ini = c.initialize()
    tl = c.list_tools() if ini.get("ok") else {"names": [], "raw": ini.get("text", "")[:800]}
    out = {"initialize_status": ini.get("status"), "tools_count": len(tl.get("names") or []),
           "tools": (tl.get("names") or [])[:60], "raw": (ini.get("text") or "")[:600]}
    save_json(NAME, "ping", out)
    return out


def call(tool: str, args: dict):
    c = _client()
    c.initialize()
    r = c.call_tool(tool, args)
    save_json(NAME, f"call_{tool.replace('__', '_')}", r)
    return r


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    if sys.argv[1] == "ping":
        print(json.dumps(ping(), ensure_ascii=False, indent=1))
    elif sys.argv[1] == "call":
        out = call(sys.argv[2], json.loads(sys.argv[3]) if len(sys.argv) > 3 else {})
        print(json.dumps({"ok": out["ok"], "isError": out["isError"], "error": out["error"]}, ensure_ascii=False))
        print(out["text"][:3000])
    else:
        print(__doc__)
