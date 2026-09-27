# -*- coding: utf-8 -*-
"""xsrc_ret.py — 换源复核**交易收益**（而非价格水平）：腾讯 qfq vs data_full（2026-09-27）"""
import json, os, pathlib, random, time
import numpy as np, pandas as pd
R = pathlib.Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
C = pathlib.Path(os.environ["PI_SCRATCH_DIR"]) / "x1cache"
recs = [json.loads(x) for x in (C / "_v_g00_trades.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
r18 = [x for x in recs if x["entry_date"] >= "2018-01-01"]
random.seed(20260927); samp = random.sample(r18, 250)
import akshare as ak
tx0 = ak.stock_zh_a_hist_tx(symbol=samp[0]["sym"], start_date="20240101", end_date="20240110", adjust="qfq")
print("腾讯返回列 =", list(tx0.columns))

def fetch(sym, d1, d2):
    for _ in range(3):
        try:
            df = ak.stock_zh_a_hist_tx(symbol=sym, start_date=d1.replace("-", ""),
                                       end_date=d2.replace("-", ""), adjust="qfq")
            df["d"] = df.iloc[:, 0].astype(str).str.slice(0, 10)
            time.sleep(0.35)
            return df
        except Exception:
            time.sleep(1.2)
    return None

def pick(df, *names):
    for n in names:
        for c in df.columns:
            if str(c).lower() == n: return c
    return None

dev, dev_gap = [], []
detail = []
miss = 0
for n, x in enumerate(samp):
    df = fetch(x["sym"], x["signal_date"], x["exit_date"])
    if df is None or len(df) == 0: miss += 1; continue
    oc, cc = pick(df, "open"), pick(df, "close", "last")
    if not (oc and cc): miss += 1; continue
    g = df.set_index("d")
    try:
        o_e = float(g.loc[x["entry_date"], oc]); c_x = float(g.loc[x["exit_date"], cc])
        c_s = float(g.loc[x["signal_date"], cc])
    except Exception:
        miss += 1; continue
    ret_df = (x.get("close_exit_px") or x["exit_px"]) / x["entry_open"] - 1.0     # data_full 两日收益（对照口径）
    ret_tx = c_x / o_e - 1.0                                                     # 腾讯 两日收益
    dev.append(ret_tx - ret_df)
    dev_gap.append((o_e / c_s - 1) - x["gap_pct"] / 100.0)
    detail.append(dict(sym=x["sym"], sig=x["signal_date"], ret_df=round(ret_df * 100, 4),
                       ret_tx=round(ret_tx * 100, 4), diff=round((ret_tx - ret_df) * 100, 4)))
    if (n + 1) % 100 == 0: print("  进度 %d/250 miss=%d" % (n + 1, miss), flush=True)

d = np.array(dev, float); gp = np.array(dev_gap, float)
print("\n=== 换源复核（2018+ 抽 250 笔；腾讯 qfq vs data_full）===")
print("  可比 %d 笔 / 跳过 %d 笔" % (d.size, miss))
print("  两日收益差 (腾讯 − data_full) 均值 %+.4f pp   中位 %+.4f pp   标准差 %.4f pp" % (
    100*d.mean(), 100*np.median(d), 100*d.std(ddof=1)))
print("  |差| > 0.3pp: %d 笔(%.1f%%)   > 1pp: %d 笔(%.1f%%)   最大 |差| %.3f pp" % (
    int((np.abs(d)>0.003).sum()), 100*(np.abs(d)>0.003).mean(),
    int((np.abs(d)>0.01).sum()), 100*(np.abs(d)>0.01).mean(), 100*np.abs(d).max()))
print("  gap 差 (腾讯 − data_full) 均值 %+.4f pp  中位 %+.4f pp  最大|差| %.4f pp" % (
    100*gp.mean(), 100*np.median(gp), 100*np.abs(gp).max()))
print("\n  ⭐ 结论判据：若「均值」接近 0 且「>1pp 占比」很小 → 数据源选择不改变结论；")
print("     若「均值」显著为正 → data_full 系统性**低估**收益（回测保守）；显著为负 → 系统性**高估**。")
print("\n  差异最大的 10 笔：")
for r in sorted(detail, key=lambda z: -abs(z["diff"]))[:10]:
    print("    %s sig=%s  data_full %+8.3f%%  腾讯 %+8.3f%%  差 %+8.3f pp" %
          (r["sym"], r["sig"], r["ret_df"], r["ret_tx"], r["diff"]))
json.dump(dict(n=int(d.size), miss=int(miss), mean_pp=round(float(100*d.mean()), 4),
               med_pp=round(float(100*np.median(d)), 4), sd_pp=round(float(100*d.std(ddof=1)), 4),
               gt03=int((np.abs(d)>0.003).sum()), gt1=int((np.abs(d)>0.01).sum()),
               max_abs_pp=round(float(100*np.abs(d).max()), 4),
               gap_mean_pp=round(float(100*gp.mean()), 4),
               detail=sorted(detail, key=lambda z: -abs(z["diff"]))[:40]),
          open(os.path.join(os.environ["PI_SCRATCH_DIR"], "xsrc_ret.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("\n[out] xsrc_ret.json")
