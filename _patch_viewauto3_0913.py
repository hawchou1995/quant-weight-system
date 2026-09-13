# -*- coding: utf-8 -*-
"""补丁 3：恢复 view-auto 视图容器（上轮误删 system_block 时丢了 <div id="view-auto"> 与三张卡）"""
import io

SRC = r"D:\Documents\Workbuddy\股票基金\quant-weight-system\build_dual_system.py"
t = io.open(SRC, encoding="utf-8").read()

start_marker = "<!-- ============ 视图 A：全量池中/长线 ============ -->"
i = t.find(start_marker)
assert i > 0, "view A marker missing"
j = t.find("\n", t.find('id="v9-retired-card"', i))
assert j > i, "retired card end missing"

new_block = """<!-- ============ 视图 A：三轨中长线（2026-09-13 起） ============ -->
<div class="view" id="view-auto">
<div class="card" id="sys-auto">
<div class="sys-head">
<div class="sys-head-top">
<h2>\U0001f6f0\ufe0f \u4e09\u8f68\u4e2d\u957f\u7ebf <span class="view-badge auto">FB3-H20 \u4e3b\u4ed3 + \u51b7\u95e8\u4f4e\u6ce2 / A4D \u53cc\u536b\u661f \u00b7 \u8d44\u91d1 60/20/20</span></h2>
</div>
<div class="sys-head-tags">
<span class="badge badge-auto">v9 \u80a1\u7968\u5206\u5c42\u6218\u6cd5\u5df2\u9000\u5f79\uff08\u5341\u91cd\u8bc1\u4f2a \u00b7 ADR-0006/0007\uff09</span>
<span class="badge badge-auto">\u4e09\u8f68\u4fe1\u53f7 = backtest/signal_satellite_0913.py \u00b7 \u6bcf\u65e5\u6536\u76d8\u8dd1</span>
<span class="badge badge-auto">\u9000\u51fa = \u5b9a\u671f\u6362\u4ed3\u5236\uff08\u8be6\u89c1\u4e0b\u65b9\u8bf4\u660e\uff09</span>
</div>
</div>
</div>
{SAT_CARD}
{SAT_PAPER_CARD}
{FB3_POOL_CARD}
<div class="card" id="v9-retired-card"><h2>\U0001f5c2\ufe0f v9 \u5168\u91cf\u6c60\uff08\u5df2\u9000\u5f79\uff09</h2><div class="sub" style="color:#ef4444">\u26d4 v9 \u80a1\u7968\u5206\u5c42\u6218\u6cd5\u4e0e 197 \u53ea\u8ddf\u8e2a\u6c60\u5df2\u4e8e 2026-09-13 \u9000\u5f79\u5e76\u79fb\u9664\u5c55\u793a\u2014\u2014\u5341\u91cd\u8bc1\u4f2a\u786e\u8ba4\u8d1f\u671f\u671b\uff08ADR-0006/0007\uff09\u3002\u5386\u53f2\u56de\u6d4b\u660e\u7ec6\u89c1\u300c\U0001f4dd \u66f4\u65b0\u65e5\u5fd7\u300dv5.9~v5.11.15 \u4e0e <code>backtest/</code> \u62a5\u544a\u5b58\u6863\u3002</div><div class="sub"><b>\u4e09\u8f68\u9000\u51fa\u89c4\u5219</b>\uff1a\u2460 \u4e3b\u4ed3 FB3-H20 = 20 \u4ea4\u6613\u65e5\u6708\u5ea6\u8f6e\u52a8 + \u725b\u718a regime \u5207\u6362\uff08\u6caa\u6df1300&lt;MA200 \u8f6c Top3 \u4f4e\u6ce2\u9632\u5b88\u4ed3\uff09\u2014\u2014<b>\u65e0\u4e2a\u80a1\u6b62\u76c8\u6b62\u635f</b>\uff08\u57fa\u91d1 NAV \u65e0\u6da8\u8dcc\u505c\uff0c\u6b62\u76c8\u53d8\u4f53\u56de\u6d4b\u5168\u90e8\u51cf\u503c\uff09\uff1b\u2461 \u51b7\u95e8\u4f4e\u6ce2 = 60 \u4ea4\u6613\u65e5\u5230\u671f\u6362\u4ed3\uff0c\u6301\u6709\u671f\u65e0\u4e2d\u9014\u64cd\u4f5c\uff1b\u2462 A4D = \u6708\u9891\u8c03\u4ed3 + \u4e2d\u8bc11000&lt;MA20 \u7ec4\u5408\u534a\u4ed3\u95f8\u3002</div></div>
</div>"""

t = t[:i] + new_block + t[j:]
io.open(SRC, "w", encoding="utf-8").write(t)
print("view-auto 容器恢复完成")
