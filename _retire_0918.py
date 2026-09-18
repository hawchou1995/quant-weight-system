# -*- coding: utf-8 -*-
"""退役收尾：① build_a5_pool.py 注释同步 ② changelog v5.13.8 置顶 ③ 页脚版本升级。"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
R = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")

# ① 注释同步
p = R / "build_a5_pool.py"
s = p.read_text(encoding="utf-8")
old = "        # 盘中 patch 标记（2026-08-28）：update_intraday_dashboard.py 盘中重写 a5_pool.js 时置 intraday=True\n        \"intraday\": False,"
new = ("        # 盘中标记：旧 update_intraday_dashboard.py（2026-09-18 退役）曾置 True；\n"
       "        # 现由客户端实时层（intraday_live.py）直接覆盖页面价格，该字段保留但恒为 False\n"
       "        \"intraday\": False,")
assert s.count(old) == 1, f"注释锚点命中 {s.count(old)}"
p.write_text(s.replace(old, new, 1), encoding="utf-8")
print("build_a5_pool.py 注释已同步")

# ② changelog
ENTRY = """## v5.13.8 - 2026-09-18（退役旧盘中链：服务端 patch + 重建 + 部署路线）

用户拍板退役。**退役前先摸清引用面**（这一步比删文件重要）：无 Windows 计划任务调用、`daily_refresh.py` 无引用、`intraday_quotes_*.json` 仅被它消费、`行情监控/`+`monitor/` 是另一套子系统（读 `raw_kline`，与本链无关）。

**删除（git rm，历史可回溯）**
- `update_intraday_dashboard.py` —— 9:30/14:30 拉快照 → patch `enhanced_data.js`/`short_pool.js`/`a5_pool.js` → 重建整页 → gh-pages 部署
- `build_intraday_0821.py` / `_build_intraday_quotes_0819.py` —— 该链的一次性产物生成器（日期写死、不可复用）
- `intraday_quotes_*.json` ×9（跟踪部分）；未跟踪的 11 份陈旧快照 + `_tmp_0909_quotes.py` 先备份到 `D:/Tools/_retired_intraday_0918/` 再删（可回退）

**替代**：客户端实时层（v5.13.7）—— 页面打开即拉行情，覆盖面更大（选股池价格/涨跌幅 + 树图全市场），且零部署、不依赖本机常开
**保留**：`行情监控/` 与 `monitor/`（独立子系统的分时数据，与本链无关）；`build_a5_pool.py` 的 `intraday` 字段机制保留（数据驱动，无人设置时恒为 False，注释已同步）

"""
p2 = R / "changelog.md"
s2 = p2.read_text(encoding="utf-8")
assert not s2.startswith("## v5.13.8"), "已存在同版本"
p2.write_text(ENTRY + s2, encoding="utf-8")
print("changelog.md: v5.13.8 已置顶")

# ③ 页脚
p3 = R / "build_dual_system.py"
s3 = p3.read_text(encoding="utf-8")
old3 = "· 版本 v5.13.7（+盘中实时数据层） · "
new3 = "· 版本 v5.13.8（+盘中实时·旧盘中链已退役） · "
assert s3.count(old3) == 1, f"页脚锚点命中 {s3.count(old3)}"
p3.write_text(s3.replace(old3, new3, 1), encoding="utf-8")
print("页脚版本 → v5.13.8")
