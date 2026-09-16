#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""connector_qcc.py —— 企查查 qcc-company 企业数据接口 · 可复用调用脚本

端点：https://agent.qcc.com/mcp/company/stream   （streamableHTTP MCP，SSE 响应）
鉴权：请求头 `Authorization: Bearer <token>`（key 见 connector-keys.json → qcc_qichacha.key）
工具：16 个（get_company_registration_info / get_shareholder_info / get_actual_controller /
      get_financial_data / get_key_personnel / get_external_investments / get_listing_info /
      get_annual_reports / get_branches / get_change_records / get_contact_info /
      get_tax_invoice_info / get_company_profile / get_company_by_query / get_beneficial_owners /
      verify_company_accuracy）
约束：searchKey 必须是完整登记名或 18 位统一社会信用代码（简称需先 get_company_by_query）
规范：限速 >=0.3s、重试 <=2、结果落 D:/Tools/cache/connectors/qcc/

用法：
    python connector_qcc.py tools
    python connector_qcc.py call get_company_registration_info "贵州茅台酒股份有限公司"
    python connector_qcc.py call verify_company_accuracy '{"name":"...","searchKey":"91..."}'
"""
import json
import sys

sys.path.insert(0, "D:/Documents/Workbuddy/股票基金/quant-weight-system/backtest")
from connector_mcp import build_client, save_json  # noqa: E402

NAME = "qcc"


def _client():
    return build_client(NAME, timeout=90)


def list_tools():
    c = _client()
    c.initialize()
    tl = c.list_tools()
    save_json(NAME, "tools", tl)
    return tl["names"]


def call(tool: str, arg):
    """arg 为 str（自动包成 searchKey）或 dict（原样传）"""
    c = _client()
    c.initialize()
    args = {"searchKey": arg} if isinstance(arg, str) else arg
    r = c.call_tool(tool, args)
    save_json(NAME, f"call_{tool}", r)
    return r


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    if sys.argv[1] == "tools":
        print(json.dumps(list_tools(), ensure_ascii=False, indent=1))
    elif sys.argv[1] == "call":
        raw = sys.argv[3] if len(sys.argv) > 3 else "{}"
        try:
            arg = json.loads(raw)
        except Exception:
            arg = raw
        out = call(sys.argv[2], arg)
        print(json.dumps({"ok": out["ok"], "isError": out["isError"],
                          "error": out["error"]}, ensure_ascii=False))
        print(out["text"][:4000])
    else:
        print(__doc__)
