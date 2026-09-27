# -*- coding: utf-8 -*-
"""falsify2.py — 用**正确**的制度约束重做证伪筛查（2026-09-27）"""
import json, os, pathlib
import numpy as np, pandas as pd
R = pathlib.Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
C = pathlib.Path(os.environ["PI_SCRATCH_DIR"]) / "x1cache"
recs = [json.loads(x) for x in (C / "_v_g00_trades.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
z = np.load(C / "panel_oos.npz", allow_pickle=True)
cal = [str(x) for x in z["cal"]]; syms = [str(x) for x in z["syms"]]
O, H, L, Cl, V, A = z["O"], z["H"], z["L"], z["C"], z["V"], z["A"]
lut = {d: i for i, d in enumerate(cal)}; jof = {s: j for j, s in enumerate(syms)}
r18 = [x for x in recs if x["entry_date"] >= "2018-01-01"]
print("样本 = 全窗 %d 笔 / 2018+ %d 笔" % (len(recs), len(r18)))

def bd(s):
    if s[:2] == "sz" and s[2:5] in ("300", "301", "302"): return 0.20
    if s[:2] == "sh" and s[2:5] == "688": return 0.20
    return 0.10

# ---- (a) 单日涨跌幅是否越过制度上限（基准 = 前收）----
bad = []
for x in recs:
    j = jof.get(x["sym"]); i = lut.get(x["entry_date"]); ie = lut.get(x["exit_date"])
    if j is None or i is None: continue
    lim = bd(x["sym"])
    for k, tag in ((i, "入场日"), (ie, "出场日")):
        if k is None or k == 0: continue
        c0, c1 = float(Cl[k - 1, j]), float(Cl[k, j])
        if c0 > 0 and c1 > 0:
            ch = c1 / c0 - 1
            if abs(ch) > lim + 0.006:      # 留 0.6pp 容差（前收可能四舍五入）
                bad.append((tag, x["signal_date"], x["sym"], round(ch * 100, 2), round(lim * 100)))
print("\n(a) 单日涨跌幅越过制度上限的 (日,标的,涨幅%%,限幅%%) 计数 = %d / %d 个出入场日（%.4f%%）"
      % (len(bad), 2 * len(recs), 100 * len(bad) / (2 * len(recs))))
for b in bad[:8]: print("     ", b)

# ---- (b) 出场日「一字板」占比（不可成交风险：一字跌停卖不掉）----
lock_up = lock_dn = 0; lock_any = 0
for x in r18:
    j = jof.get(x["sym"]); ie = lut.get(x["exit_date"])
    if j is None or ie is None: continue
    o, h, l, c = float(O[ie, j]), float(H[ie, j]), float(L[ie, j]), float(Cl[ie, j])
    if o == h == l == c and o > 0:
        lock_any += 1
        ch = c / float(Cl[ie - 1, j]) - 1 if float(Cl[ie - 1, j]) > 0 else 0
        if ch > 0.05: lock_up += 1
        elif ch < -0.05: lock_dn += 1
print("\n(b) 2018+ 出场日为一字板（O=H=L=C）: %d 笔（%.2f%%）——其中 涨板 %d / **跌板 %d（卖不掉 → 回测高估）**"
      % (lock_any, 100 * lock_any / len(r18), lock_up, lock_dn))

# ---- (c) 入场日收盘涨停 的交易占比与收益贡献 ----
zt, zt_ret, other_ret = [], 0.0, 0.0
for x in r18:
    j = jof.get(x["sym"]); i = lut.get(x["entry_date"])
    if j is None or i is None: continue
    lim = bd(x["sym"])
    c0, c1 = float(Cl[i - 1, j]), float(Cl[i, j])
    is_zt = (c0 > 0 and c1 / c0 - 1 >= lim - 0.006)
    if is_zt:
        zt.append(x["ret_pct"]); zt_ret += x["ret_pct"]
    else:
        other_ret += x["ret_pct"]
print("\n(c) 入场日（T+1）收盘封涨停的交易: %d 笔（%.2f%%）· 这些笔净均 %+.3f%% · 其收益占全部收益的 %.1f%%"
      % (len(zt), 100 * len(zt) / len(r18), np.mean(zt) if zt else 0, 100 * zt_ret / (zt_ret + other_ret)))
non = [x["ret_pct"] for x in r18 if x["ret_pct"] is not None]
# 剔除涨停笔后的净均
keep = []
for x in r18:
    j = jof.get(x["sym"]); i = lut.get(x["entry_date"])
    if j is None or i is None: keep.append(x["ret_pct"]); continue
    lim = bd(x["sym"]); c0, c1 = float(Cl[i - 1, j]), float(Cl[i, j])
    if not (c0 > 0 and c1 / c0 - 1 >= lim - 0.006): keep.append(x["ret_pct"])
print("    剔除「T+1 封涨停」后 2018+ 净均 = %+.4f%%（原 %+.4f%%），笔数 %d → %d"
      % (np.mean(keep), np.mean(non), len(non), len(keep)))

# ---- (d) TP 口径依赖：把止盈假设改成「T+2 收盘价无条件卖出」----
alt = np.array([x.get("ret_pct_close", x["ret_pct"]) for x in r18], float)
cur = np.array([x["ret_pct"] for x in r18], float)
print("\n(d) 出场口径敏感性（2018+，同批信号）：")
print("    主口径（止盈+2%%/未达标 T+2 尾盘）净均 %+.4f%% 中位 %+.4f%% 胜率 %.2f%%" % (cur.mean(), np.median(cur), 100 * (cur > 0).mean()))
print("    纯 T+2 尾盘（无止盈）            净均 %+.4f%% 中位 %+.4f%% 胜率 %.2f%%" % (alt.mean(), np.median(alt), 100 * (alt > 0).mean()))
print("    差（止盈贡献） = %+.4f pp/笔" % (cur.mean() - alt.mean()))

# ---- (e) 收益是否依赖少数几天（同日多笔）----
byday = {}
for x in r18: byday.setdefault(x["entry_date"], []).append(x["ret_pct"])
dm = np.array([np.mean(v) for v in byday.values()])
print("\n(e) 按入场日聚合：%d 天 · 日均 %+.4f%% · 日胜率 %.1f%%" % (dm.size, dm.mean(), 100 * (dm > 0).mean()))
top = np.sort(dm)[::-1]
print("    最好 10 个入场日贡献 = %.1f%% 的日收益合计；最好 5%% 的天数贡献 = %.1f%%"
      % (100 * top[:10].sum() / dm.sum(), 100 * top[:int(0.05 * dm.size)].sum() / dm.sum()))
