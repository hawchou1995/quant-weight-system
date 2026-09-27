# -*- coding: utf-8 -*-
"""falsify_hpdk.py — 对「横盘低开」年化做证伪筛查（2026-09-27）

不重新解释结论，只找**能推翻它**的证据：异常值、集中度、复牌/停牌、微盘集中、原始数据核对。
数据源：_v_g00_trades.jsonl（主板冻结规格重放，23,759 笔）+ panel_oos.npz + data_full 原始 CSV。
"""
import json, os, pathlib
import numpy as np

R = pathlib.Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
C = pathlib.Path(os.environ["PI_SCRATCH_DIR"]) / "x1cache"
recs = [json.loads(x) for x in (C / "_v_g00_trades.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
print("逐笔 =", len(recs))
z = np.load(C / "panel_oos.npz", allow_pickle=True)
cal = [str(x) for x in z["cal"]]; syms = [str(x) for x in z["syms"]]
A, Cc, O = z["A"], z["C"], z["O"]
lut = {d: i for i, d in enumerate(cal)}; jof = {s: j for j, s in enumerate(syms)}
AMT20 = __import__("pandas").DataFrame(np.where((Cc > 0), A, np.nan)).rolling(20, min_periods=10).mean().to_numpy()

def sub(rs, lo="2018-01-01"):
    return [x for x in rs if x["entry_date"] >= lo]

def stat(rs, tag):
    r = np.array([x["ret_pct"] for x in rs], float)
    print("\n=== %s  n=%d ===" % (tag, r.size))
    print("  净均 %+.4f%%  净中位 %+.4f%%  胜率 %.2f%%" % (r.mean(), np.median(r), 100 * (r > 0).mean()))
    for q in (1, 5, 25, 50, 75, 95, 99):
        print("    p%-2d %+9.4f%%" % (q, np.percentile(r, q)), end="")
        if q in (1, 5): print()
    print("\n  最小 %+.4f%%  最大 %+.4f%%" % (r.min(), r.max()))
    print("  |ret|>21%%（主板 2 日制度上限外）: %d 笔 (%.4f%%)" % ((np.abs(r) > 21).sum(), 100 * (np.abs(r) > 21).mean()))
    print("  ret>+15%%: %d 笔 (%.3f%%)   ret<-15%%: %d 笔 (%.3f%%)"
          % ((r > 15).sum(), 100 * (r > 15).mean(), (r < -15).sum(), 100 * (r < -15).mean()))
    s = np.sort(r)[::-1]
    tot = r.sum()
    for n in (1, 10, 50, int(0.01 * r.size)):
        print("  前 %-5d 笔收益合计占比 = %6.2f%%" % (n, 100 * s[:n].sum() / tot))
    return r

r_all = stat(recs, "全窗 2015-2026")
r18 = stat(sub(recs), "2018+")

# ---- 去掉最好一年 / 去掉最好 1% 笔 后的「每笔净均」变化 ----
yrs = {}
for x in recs:
    yrs.setdefault(x["entry_date"][:4], []).append(x["ret_pct"])
print("\n=== 分年 每笔净均（笔数） ===")
for y in sorted(yrs):
    a = np.array(yrs[y], float)
    print("  %s  %+8.4f%%  (n=%d)" % (y, a.mean(), a.size))
y18 = {k: v for k, v in yrs.items() if k >= "2018"}
best = max(y18, key=lambda k: np.mean(y18[k]))
print("  2018+ 每年净均最高的一年 = %s（%+.4f%%）；剔除它后 2018+ 净均 = %+.4f%%"
      % (best, np.mean(y18[best]), np.mean([v for k, vs in y18.items() if k != best for v in vs])))
arr = np.array([x["ret_pct"] for x in sub(recs)], float)
k99 = int(0.99 * arr.size)
print("  剔除收益最高的 1%% 笔（%d 笔）后 2018+ 净均 = %+.4f%%" % (arr.size - k99, np.sort(arr)[:k99].mean()))

# ---- 复牌/停牌/极端成交筛查 ----
print("\n=== 停牌复牌 / 极端成交筛查（2018+） ===")
susp = []
for x in sub(recs):
    j = jof.get(x["sym"]); 
    if j is None: continue
    for d in (x["entry_date"], x["exit_date"]):
        i = lut.get(d)
        if i is None: continue
        a20 = AMT20[i, j]
        if np.isfinite(a20) and a20 > 0:
            ratio = float(A[i, j]) / float(a20)
            if ratio > 8: susp.append((d, x["sym"], round(ratio, 1), x["ret_pct"]))
            if ratio < 0.05: susp.append((d, x["sym"], round(ratio, 2), x["ret_pct"]))
print("  成交额 / 20日均额 超 8 倍 或 低于 0.05 倍的 (日,标的) 样本数 = %d（占出入场对 %d 的 %.3f%%）"
      % (len(susp), 2 * len(sub(recs)), 100 * len(susp) / (2 * len(sub(recs)))))
for s in susp[:6]:
    print("     ", s)

# ---- 微盘集中度：按信号日 ADV20 分位看收益 ----
print("\n=== 按信号日 20日均额 分档（2018+） ===")
rows = []
for x in sub(recs):
    j = jof.get(x["sym"]); i = lut.get(x["signal_date"])
    if j is None or i is None: continue
    rows.append((float(AMT20[i, j]) if np.isfinite(AMT20[i, j]) else np.nan, x["ret_pct"]))
rows = [(a, r) for a, r in rows if np.isfinite(a)]
a_arr = np.array([a for a, _ in rows]); r_arr = np.array([r for _, r in rows], float)
q = np.percentile(a_arr, [0, 10, 25, 50, 75, 90, 100])
print("  ADV 分位(万): " + "  ".join("%.0f" % (v / 1e4) for v in q))
for k in range(len(q) - 1):
    m = (a_arr >= q[k]) & (a_arr <= q[k + 1])
    if m.sum():
        print("  [%8.0f万 ~ %8.0f万]  n=%5d  净均 %+8.4f%%  胜率 %.2f%%"
              % (q[k] / 1e4, q[k + 1] / 1e4, m.sum(), r_arr[m].mean(), 100 * (r_arr[m] > 0).mean()))

# ---- 最大赢家逐笔 + 原始数据核对 ----
print("\n=== 2018+ 收益最高的 12 笔（含原始数据核对） ===")
top = sorted(sub(recs), key=lambda x: -x["ret_pct"])[:12]
for x in top:
    j = jof.get(x["sym"]); 
    p = R / "data_full" / (x["sym"] + ".csv")
    raw = ""
    if p.exists():
        try:
            import csv as _csv
            keep = {}
            with open(p, encoding="utf-8") as fh:
                for row in _csv.DictReader(fh):
                    d = str(row["date"])[:10]
                    if d in (x["signal_date"], x["entry_date"], x["exit_date"]):
                        keep[d] = row
            for d in (x["signal_date"], x["entry_date"], x["exit_date"]):
                if d in keep:
                    k = keep[d]
                    raw += " %s O=%s C=%s H=%s L=%s V=%s" % (d[5:], k.get("open"), k.get("close"),
                                                            k.get("high"), k.get("low"), k.get("volume"))
        except Exception as e:
            raw = " <读取失败 %r>" % (e,)
    print("  %s %s  sig=%s ent=%s@%.3f exit=%s@%.3f  净 %+.3f%%" %
          (x["sym"], ("gap %+.2f%%" % x["gap_pct"]), x["signal_date"], x["entry_date"],
           x["entry_open"], x["exit_date"], x["exit_px"], x["ret_pct"]))
    print("      原始:" + raw[:220])
