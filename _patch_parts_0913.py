# -*- coding: utf-8 -*-
"""补丁 6：评分列升级为「总分 + 各子项得分」（轨A 额/波两项；轨B 六因子贡献）"""
import io

# ---- A. build_satellite_pool.py ----
P1 = r"D:\Documents\Workbuddy\股票基金\quant-weight-system\backtest\build_satellite_pool.py"
t1 = io.open(P1, encoding="utf-8").read()

old_a = """    sc = round(50 * (amt_pct[c] + atr_pct[c]), 1)     # 0-100 合成分
    ln_rows.append({
        "code": c, "name": nm(c), "industry": rd(c),
        "close": round(float(d["close"]), 2), "lot": round(float(d["close"]) * 100),
        "score_txt": f"{sc:.0f}", "score": sc,
        "detail": f"额分位{amt_pct[c]:.0%}·波分位{atr_pct[c]:.0%}（双低合分越高越冷门低波）","""
assert old_a in t1, "A rows block missing"
new_a = """    p_amt = round(50 * amt_pct[c], 1); p_atr = round(50 * atr_pct[c], 1)
    sc = round(p_amt + p_atr, 1)
    ln_rows.append({
        "code": c, "name": nm(c), "industry": rd(c),
        "close": round(float(d["close"]), 2), "lot": round(float(d["close"]) * 100),
        "score_txt": f"{sc:.0f}", "score": sc,
        "parts": f"额 {p_amt:.0f} · 波 {p_atr:.0f}（各 0-50）",
        "detail": f"额分位{amt_pct[c]:.0%}·波分位{atr_pct[c]:.0%}（双低合分越高越冷门低波）","""
t1 = t1.replace(old_a, new_a, 1)

old_b = """    contrib = sorted(((k, float(zmap[k][j]) * W[k]) for k in picked), key=lambda x: -abs(x[1]))
    detail = "｜".join(f"{k} {v:+.2f}" for k, v in contrib[:3])
    a4_rows.append({
        "code": c, "name": nm(c), "industry": rd(c),
        "close": round(clse, 2), "lot": round(clse * 100),
        "score_txt": f"{sc_row[j]:.2f}", "score": round(float(sc_row[j]), 2),
        "detail": f"icir复合分（z·权重前三：{detail}）","""
assert old_b in t1, "B rows block missing"
new_b = """    contrib = sorted(((k, float(zmap[k][j]) * W[k]) for k in picked), key=lambda x: -abs(x[1]))
    _lbl = {"amount20": "额", "size_rev": "市反", "amp20": "振", "ret60": "动60", "bp": "BP", "size_ep": "EP"}
    parts = " · ".join(f"{_lbl.get(k, k)} {v:+.2f}" for k, v in contrib)
    detail = "｜".join(f"{k} {v:+.2f}" for k, v in contrib[:3])
    a4_rows.append({
        "code": c, "name": nm(c), "industry": rd(c),
        "close": round(clse, 2), "lot": round(clse * 100),
        "score_txt": f"{sc_row[j]:.2f}", "score": round(float(sc_row[j]), 2),
        "parts": parts,
        "detail": f"icir复合分（z·权重：{detail}…）","""
t1 = t1.replace(old_b, new_b, 1)
io.open(P1, "w", encoding="utf-8").write(t1)
print("build_satellite_pool: parts 字段完成")

# ---- B. build_dual_system.py：评分单元格渲染 ----
P2 = r"D:\Documents\Workbuddy\股票基金\quant-weight-system\build_dual_system.py"
t2 = io.open(P2, encoding="utf-8").read()
old_cell = """            f'<td title="{r.get("detail", "")}">{r.get("score_txt", "—")}</td>'"""
assert old_cell in t2, "score cell missing"
new_cell = """            f'<td title="{r.get("detail", "")}"><b>{r.get("score_txt", "—")}</b><div style="font-size:10.5px;color:#94a3b8;line-height:1.35;white-space:normal;max-width:190px">{r.get("parts", "")}</div></td>'"""
t2 = t2.replace(old_cell, new_cell, 1)
old_th = "<th>评分·拆解(悬浮)</th>"
assert old_th in t2, "th missing"
t2 = t2.replace(old_th, "<th>评分 = 总分 + 子项</th>", 1)
io.open(P2, "w", encoding="utf-8").write(t2)
print("build_dual_system: 评分单元格完成")
