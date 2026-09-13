# -*- coding: utf-8 -*-
"""补丁 5：SAT 表升级（计划金额/评分拆解/操作/排序说明）+ FB3 卡（权重/操作）"""
import io

SRC = r"D:\Documents\Workbuddy\股票基金\quant-weight-system\build_dual_system.py"
t = io.open(SRC, encoding="utf-8").read()

# A. tds 行模板
old_tds = """        tds = "".join(
            f'<tr><td><code>{r["code"]}</code></td><td>{r.get("name", "")}</td><td>{r.get("industry", "—")}</td><td class="num">{r["close"]:.2f}</td>'
            f'<td class="num">{r["lot"]:,} 元</td>'
            + ('<td class="num" style="color:#d97706">涨停勿追</td>' if r.get("limit_guard") else '<td class="num">—</td>')
            + "</tr>"
            for r in tr["rows"])"""
assert old_tds in t, "tds block missing"
new_tds = """        tds = "".join(
            f'<tr><td><code>{r["code"]}</code></td><td>{r.get("name", "")}</td><td>{r.get("industry", "—")}</td><td class="num">{r["close"]:.2f}</td>'
            f'<td class="num">{r["lot"]:,} 元</td><td class="num">{r.get("amount", 0):,} 元</td>'
            f'<td title="{r.get("detail", "")}">{r.get("score_txt", "—")}</td>'
            f'<td>{r.get("action", "—")}{" ⚠涨停勿追" if r.get("limit_guard") else ""}</td>'
            + "</tr>"
            for r in tr["rows"])"""
t = t.replace(old_tds, new_tds, 1)

# B. sub 行加排序说明
old_sub = """        return (f'<div class="sub" style="margin:6px 0"><b>{tr["name"]}</b> · 调仓：{tr["rebal"]}{cal_note}'
                f'｜回测 +{bt["total"]}%/年化 +{bt["ann"]}%/回撤 {bt["mdd"]}%/夏普 {bt["sharpe"]}</div>'"""
assert old_sub in t, "sat sub missing"
new_sub = """        return (f'<div class="sub" style="margin:6px 0"><b>{tr["name"]}</b> · {tr.get("ranking", "")}</div>'
                f'<div class="sub" style="margin:6px 0">调仓：{tr["rebal"]}{cal_note}'
                f'｜回测 +{bt["total"]}%/年化 +{bt["ann"]}%/回撤 {bt["mdd"]}%/夏普 {bt["sharpe"]}</div>'"""
t = t.replace(old_sub, new_sub, 1)

# C. 表头
old_th = "<th>代码</th><th>名称</th><th>行业</th><th>收盘</th><th>一手约</th><th>守卫</th>"
assert old_th in t, "sat header missing"
t = t.replace(old_th, "<th>代码</th><th>名称</th><th>行业</th><th>收盘</th><th>一手约</th><th>计划金额</th><th>评分·拆解(悬浮)</th><th>操作</th>", 1)

# D. SAT 卡说明追加
old_note = "目标持仓为<b>下次调仓的完整清单</b>（非增量）</div>"
assert old_note in t
t = t.replace(old_note, "目标持仓为<b>下次调仓的完整清单</b>（非增量）· 评分列悬浮可见拆解 · 操作列=相对模拟盘当前持仓</div>", 1)

# E. FB3 卡：权重/操作
old_fund = """_fund_rows = ""
for _c in _fund_tier:
    _d = _sp_j.get("details", {}).get(_c, {})
    _fund_rows += (f'<tr><td><code>{_c}</code></td><td>{_d.get("name", "")}</td>'
                   f'<td class="num">{_d.get("score", "—")}</td><td>{_d.get("pool", "fund")}</td></tr>')"""
assert old_fund in t, "fund rows block missing"
new_fund = """_held_c = set()
try:
    _hst = json.load(open(BASE / "backtest" / "holdings_satellite.json", encoding="utf-8"))
    _held_c = set((_hst.get("track_c", {}) or {}).get("holdings", {}).keys())
except Exception:
    pass
_n_f = max(1, len(_fund_tier))
_fund_rows = ""
for _c in _fund_tier:
    _d = _sp_j.get("details", {}).get(_c, {})
    _act = "持有" if _c in _held_c else "申购"
    _fund_rows += (f'<tr><td><code>{_c}</code></td><td>{_d.get("name", "")}</td>'
                   f'<td class="num">{_d.get("score", "—")}</td><td class="num">{100/_n_f:.1f}%</td><td>{_act}</td></tr>')"""
t = t.replace(old_fund, new_fund, 1)

old_fh = "<thead><tr><th>代码</th><th>名称</th><th>动量分</th><th>池</th></tr></thead>"
assert old_fh in t, "fund header missing"
t = t.replace(old_fh, "<thead><tr><th>代码</th><th>名称</th><th>动量分</th><th>权重</th><th>操作</th></tr></thead>", 1)
t = t.replace("空（门控关闭）</td></tr>", "空（门控关闭；基金轨熊市照买 Top3）</td></tr>", 1)
old_fsub = "<div class=\"sub\">市况门控 {_gate_txt} · 60% 资金 · 牛市 Top10 动量 / 熊市 Top3 低波（C 类份额，T+1 净值申赎）</div>"
assert old_fsub in t, "fund sub missing"
t = t.replace(old_fsub, "<div class=\"sub\">排序=基金动量分降序 · 市况门控 {_gate_txt} · 60% 资金 · 牛市 Top10 动量 / 熊市 Top3 低波（C 类份额，T+1 净值申赎）· 操作=相对模拟盘当前持仓</div>", 1)

io.open(SRC, "w", encoding="utf-8").write(t)
print("补丁5 写盘完成")
