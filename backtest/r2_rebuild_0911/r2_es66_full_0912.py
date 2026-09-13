# -*- coding: utf-8 -*-
"""r2 · 66 公式全量事件研究（主板宇宙，k=20/40/60，成本阶梯）（2026-09-12）
================================================================
Grill R1 根决策（用户拍板）：素材驱动全量筛选重建；66公式全量先行；
中长线窗口 20/40/60 日；成本铁律 1.15% 往返 + 阶梯 {0.3, 1.15, 2.0}%；
零候选即关闭结案（边界预注册，不接受事后无限改参）。

管线：
  A) 编译 66 公式全部 select 块（tdx_interp 迷你解释器）→ 编译回执
  B) 交叉验证：解释器 vs 13 个手译信号（naci_event_study_66_0911.compute_signals）
     150 只样本股，逐信号统计总计数比 + 逐日重合率；匹配率<90% 的信号给出对照
  C) 全量：主板（sh60*/sz00*）事件研究——信号日收盘确认→T+1开盘买→T+1+k开盘卖
     edge = 逐日(信号均值−同日主板基线均值) 等权平均（毛）；净 edge = 毛 − 成本
  D) 预注册筛选：
     过闸 = 净115(k) > 0 对某 k∈{20,40,60} 且 pos_fwd_rate≥50% 且 n_days≥100 且 n≥1000
     观察 = 净03(k) > 0 但净115 全 ≤0
输出：r2_rebuild_0911/es66_full.csv / es66_survivors.csv / compile_receipt.json /
     validate_13.json / survivors_daily_counts.npz（组合级+安慰剂输入）
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(r"D:\Documents\Workbuddy\股票基金\quant-weight-system")
R2 = BASE / "backtest" / "r2_rebuild_0911"
OUT = BASE / "backtest" / "naci_sentiment_0911_out"
R2.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(R2))
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "backtest"))

import tdx_interp as T  # noqa: E402
import v8_selector as V  # noqa: E402

KS = (20, 40, 60)
COSTS = {"net03": 0.3, "net115": 1.15, "net20": 2.0}
MIN_BASE = 50

# ---- A) 编译（同 serial 兄弟块上下文合并重试：跨块变量引用/"最后一句修改成"模式） ----
data = json.load(open(Path(r"D:\Documents\Workbuddy\股票基金\formula_lib\formulas_66.json"), encoding="utf-8"))
formulas = []   # dicts: serial, variant, label, ast, local, flags
receipt = {"compiled": [], "skipped": []}
for it in data["items"]:
    ctx = ""
    for bi, b in enumerate(it.get("blocks", [])):   # ctx 用全部块（含副图）
        code = b["code"]
        if b.get("kind") == "select":
            key = f"{it['serial']}.{it.get('select_blocks', []).index(b) if b in it.get('select_blocks', []) else bi}"
        try:
            is_select = b in it.get("select_blocks", [])
        except Exception:
            is_select = False
        if is_select:
            vi = it["select_blocks"].index(b)
            key = f"{it['serial']}.{vi}"
            # 信号名写在 label、code 以操作符/关键词开头 → 用 label 作表达式头
            cand = code
            head = code.strip()[:4].upper()
            if head.startswith(("AND", "OR", "NOT")) or (head[:1] in "+-*/(<>="):
                cand = (b.get("label") or "").replace("：", ":").strip() + "\n" + code
            try:
                ast, local, flags = T.compile_block(cand)
            except NotImplementedError as e:
                if "unknown var" in str(e) and ctx:
                    try:
                        ast, local, flags = T.compile_block(ctx + "\n" + cand)
                    except Exception as e2:
                        receipt["skipped"].append({"key": key, "label": (b.get("label") or "")[:40],
                                                   "reason": f"ctx-retry {type(e2).__name__}: {e2}"[:200]})
                        ctx += "\n" + code
                        continue
                else:
                    receipt["skipped"].append({"key": key, "label": (b.get("label") or "")[:40],
                                               "reason": f"{type(e).__name__}: {e}"[:200]})
                    ctx += "\n" + code
                    continue
            except Exception as e:
                receipt["skipped"].append({"key": key, "label": (b.get("label") or "")[:40],
                                           "reason": f"{type(e).__name__}: {e}"[:200]})
                ctx += "\n" + code
                continue
            formulas.append({"key": key, "serial": it["serial"], "variant": vi,
                             "label": (b.get("label") or "")[:40], "ast": ast,
                             "local": local, "flags": flags})
            receipt["compiled"].append({"key": key, "label": (b.get("label") or "")[:40]})
        ctx += "\n" + code
print(f"[compile] {len(receipt['compiled'])} 编译 / {len(receipt['skipped'])} 跳过", flush=True)
for s in receipt["skipped"]:
    print(f"  skip {s['key']} {s['label']}: {s['reason']}", flush=True)

# 已知退化公式修正对照臂：7.1 原文 涨幅:=C/REF(C,1) 缺 -1（恒真）→ 修正为差值后 >0.04
try:
    it7 = next(it for it in data["items"] if it["serial"] == 7)
    code71 = it7["select_blocks"][1]["code"].replace("涨幅:=C/REF(C,1)", "涨幅:=C/REF(C,1)-1")
    ast71, local71, flags71 = T.compile_block(code71)
    formulas.append({"key": "7.1c", "serial": 7, "variant": 1,
                     "label": "一阳穿多线(涨幅修正)", "ast": ast71,
                     "local": local71, "flags": flags71})
    receipt["compiled"].append({"key": "7.1c", "label": "一阳穿多线(涨幅修正)",
                                "note": "原文涨幅:=C/REF(C,1) 恒真（作者笔误）→ 修正为 -1 差值，n_trials+1 如实申报"})
    print("[compile] +7.1c 修正对照臂", flush=True)
except Exception as e:
    print(f"[compile] 7.1c 修正失败: {e}", flush=True)


def eval_formula(f, df):
    c = df["close"].to_numpy(float); o = df["open"].to_numpy(float)
    h = df["high"].to_numpy(float); l = df["low"].to_numpy(float)
    v = df["volume"].to_numpy(float); amo = df["amount"].to_numpy(float)
    env = {"CLOSE": c, "C": c, "OPEN": o, "O": o, "HIGH": h, "H": h,
           "LOW": l, "L": l, "VOL": v, "V": v, "VOLUME": v,
           "AMO": amo, "AMOUNT": amo, "DRAWNULL": np.nan}
    with np.errstate(invalid="ignore", divide="ignore"):
        for name, ast in f["local"].items():
            if name.startswith("__anon"):
                continue
            env[name] = T.ev(ast, env)
        sig = T.ev(f["ast"], env)
    return np.asarray(sig, float) != 0


# ---- B) 交叉验证（13 手译 vs 解释器） ----
def load_hand_module():
    import types
    src = open(BASE / "backtest" / "naci_event_study_66_0911.py", encoding="utf-8").read()
    src = src.split('if __name__ == "__main__":')[0]
    mod = types.ModuleType("hand")
    exec(compile(src, "hand", "exec"), mod.__dict__)
    return mod


HAND_MAP = {1: [1], 2: [0], 3: [0], 6: [0], 7: [1], 8: [0], 9: [0], 11: [0],
            15: [0], 16: [0], 17: [0], 20: [0], 21: [0]}
HAND_NAME = {1: "01_KDJ超跌", 2: "02_MACD金叉", 3: "03_三金叉共振", 6: "06_MACD底背离",
             7: "07_均线粘合突破", 8: "08_单阳不破", 9: "09_涨停回马枪", 11: "11_均线多头",
             15: "15_极阴次阳", 16: "16_超跌阳包阴", 17: "17_缺口不回补", 20: "20_老鸭头",
             21: "21_W底"}


def validate(pool_sample, hand):
    rows = []
    fby = {f["serial"]: f for f in formulas if f["variant"] in HAND_MAP.get(f["serial"], [])}
    for code, df in pool_sample.items():
        df = df.dropna(subset=["close"])
        if len(df) < 400:
            continue
        try:
            hand_sigs = hand.compute_signals(df)
        except Exception:
            continue
        for serial, vi in HAND_MAP.items():
            f = fby.get(serial)
            if f is None:
                continue
            try:
                isig = eval_formula(f, df).astype(int)
            except Exception:
                continue
            hsig = hand_sigs[HAND_NAME[serial]].astype(int)
            inter = int(((isig == 1) & (hsig == 1)).sum())
            union = int(((isig == 1) | (hsig == 1)).sum())
            rows.append({"serial": serial,
                         "interp": int(isig.sum()), "hand": int(hsig.sum()),
                         "jaccard": round(inter / union, 3) if union else 1.0})
    g = pd.DataFrame(rows).groupby("serial").agg(
        interp=("interp", "sum"), hand=("hand", "sum"), jaccard=("jaccard", "mean")).reset_index()
    return g


# ---- C) 全量事件研究 ----
def fwd_returns(op):
    op = pd.Series(op, dtype=float)
    base = op.shift(-1)
    return {k: (op.shift(-(1 + k)) / base - 1).to_numpy() for k in KS}


if __name__ == "__main__":
    t0 = time.time()
    pool = V.load_pool(use_cache=True)
    main_codes = [c for c in pool if c.startswith(("sh60", "sz00"))]
    print(f"[pool] {len(pool)} 只，主板 {len(main_codes)} 只", flush=True)

    # 验证（150 只样本）
    hand = load_hand_module()
    sample = {c: pool[c] for c in main_codes[:150]}
    g = validate(sample, hand)
    bad = g[g["jaccard"] < 0.9]
    print("[validate-13]", flush=True)
    print(g.to_string(index=False), flush=True)
    json.dump({"table": g.to_dict("records"),
               "n_below_090": int(len(bad))},
              open(R2 / "validate_13.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # 全量
    all_dates = pd.DatetimeIndex([])
    for code in main_codes:
        all_dates = all_dates.append(pool[code].index)
    all_dates = all_dates.unique().sort_values()
    dpos = pd.Series(np.arange(len(all_dates)), index=all_dates)
    n_d = len(all_dates)
    base_sum = {k: np.zeros(n_d) for k in KS}
    base_cnt = {k: np.zeros(n_d, dtype=np.int64) for k in KS}
    sig_sum = {f["key"]: {k: np.zeros(n_d) for k in KS} for f in formulas}
    sig_cnt = {f["key"]: {k: np.zeros(n_d, dtype=np.int64) for k in KS} for f in formulas}
    day_cnt = {f["key"]: np.zeros(n_d, dtype=np.int64) for f in formulas}

    done = n_err = 0
    for code in main_codes:
        df = pool[code].dropna(subset=["close"])
        if len(df) < 400:
            continue
        pos = dpos.reindex(df.index).to_numpy()
        ok = ~np.isnan(pos)
        if ok.sum() < 400:
            continue
        pos = pos[ok].astype(np.int64)
        dfo = df.loc[df.index[ok]]
        op = dfo["open"].to_numpy(float)
        fwd = fwd_returns(op)
        for f in formulas:
            try:
                s = eval_formula(f, dfo)
            except Exception:
                n_err += 1
                continue
            for k in KS:
                m = s & np.isfinite(fwd[k])
                np.add.at(sig_sum[f["key"]][k], pos[m], fwd[k][m])
                np.add.at(sig_cnt[f["key"]][k], pos[m], 1)
            np.add.at(day_cnt[f["key"]], pos[s], 1)
        for k in KS:
            fk = fwd[k]
            valid = np.isfinite(fk)
            np.add.at(base_sum[k], pos[valid], fk[valid])
            np.add.at(base_cnt[k], pos[valid], 1)
        done += 1
        if done % 500 == 0:
            print(f"  [run] {done} 只 ({time.time()-t0:.0f}s)", flush=True)

    rows = []
    for f in formulas:
        for k in KS:
            sc = sig_cnt[f["key"]][k].astype(float)
            bc = base_cnt[k].astype(float)
            sm = np.where(sc > 0, sig_sum[f["key"]][k] / np.maximum(sc, 1), np.nan)
            bm = np.where(bc >= MIN_BASE, base_sum[k] / np.maximum(bc, 1), np.nan)
            edge = sm - bm
            okm = np.isfinite(edge) & (sc >= 5)
            if okm.sum() < 20:
                continue
            gross = float(np.nanmean(edge[okm])) * 100
            row = {"key": f["key"], "serial": f["serial"], "variant": f["variant"],
                   "label": f["label"], "k": k,
                   "n_signals": int(sc.sum()), "n_days": int(okm.sum()),
                   "base_mean_pct": round(float(np.nanmean(bm[okm])) * 100, 3),
                   "sig_mean_pct": round(float(np.nansum(sig_sum[f["key"]][k]) / max(1, sc.sum())) * 100, 3),
                   "gross_edge_pct": round(gross, 3),
                   "pos_fwd_rate_pct": round(float(np.mean(sm[okm] > 0) * 100), 1),
                   "edge_hit_rate_pct": round(float(np.mean(edge[okm] > 0) * 100), 1)}
            for cn, cv in COSTS.items():
                row[cn + "_pct"] = round(gross - cv, 3)
            rows.append(row)
    res = pd.DataFrame(rows)
    res.to_csv(R2 / "es66_full.csv", index=False, encoding="utf-8")

    # 预注册筛选（在 k 维度上取每个公式最优行）
    best = (res.sort_values("gross_edge_pct", ascending=False)
               .groupby("key", as_index=False).first())
    surv = best[(best["net115_pct"] > 0) & (best["pos_fwd_rate_pct"] >= 50)
                & (best["n_days"] >= 100) & (best["n_signals"] >= 1000)]
    watch = best[(best["net03_pct"] > 0) & (best["net115_pct"] <= 0)]
    surv.to_csv(R2 / "es66_survivors.csv", index=False, encoding="utf-8")
    watch.to_csv(R2 / "es66_watch.csv", index=False, encoding="utf-8")

    # 幸存者逐日信号数（组合级/安慰剂输入）
    np.savez_compressed(R2 / "survivors_daily_counts.npz",
                        dates=[str(d.date()) for d in all_dates],
                        **{r["key"]: day_cnt[r["key"]] for _, r in surv.iterrows()})

    receipt["n_formulas"] = len(formulas)
    receipt["n_mainboard"] = len(main_codes)
    receipt["executed"] = done
    receipt["eval_errors"] = n_err
    receipt["date_range"] = [str(all_dates[0].date()), str(all_dates[-1].date())]
    receipt["screen"] = {"pass": surv["key"].tolist(), "watch": watch["key"].tolist()}
    json.dump(receipt, open(R2 / "compile_receipt.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"\n[done] 编译 {len(receipt['compiled'])}/{len(receipt['compiled'])+len(receipt['skipped'])} "
          f"错误评估 {n_err} | 过闸 {len(surv)} 观察 {len(watch)} | {time.time()-t0:.0f}s", flush=True)
    if len(surv):
        print(surv[["key", "label", "k", "n_signals", "gross_edge_pct", "net115_pct",
                    "pos_fwd_rate_pct"]].to_string(index=False), flush=True)
    if len(watch):
        print("[watch]", flush=True)
        print(watch[["key", "label", "k", "n_signals", "gross_edge_pct", "net03_pct"]].head(20).to_string(index=False), flush=True)
