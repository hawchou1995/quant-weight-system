# -*- coding: utf-8 -*-
"""A5 打板模拟盘（2026-09-14 建立，三系统模拟盘补齐的最后一块）
口径：生产 P0（低开打板）——昨日涨停 ∧ 今日 gap∈(-5%,-2%) ∧ rp(60日位置)≤0.5
     → T 日开盘买入 → tp_t2 出场（T+1/T+2 high≥entry×1.08 止盈；涨停顺延；否则收盘卖；T+2 强平）
机制：逐笔影子账本（state json）——每次跑扫描最新交易日候选 + 对 pending 检查出场 + 等权净值
复用：strategy_absorb_ev3_a5_absorb 的生产模块（零复刻偏差）
用法：python backtest/a5_paper_0914.py    # 每日收盘后跑
状态：backtest/a5_paper_state.json
"""
import sys, json, time
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent  # 2026-09-24 云端可移植（原写死 D:/…，本机解析恒等）
sys.path.insert(0, str(BASE))
import strategy_absorb_ev3_a5_absorb as A5

STATE = BASE / "backtest" / "a5_paper_state.json"
GAP = (-0.05, -0.02)   # P0 生产
RP_MAX = 0.5
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)

_nh = pd.read_csv(BASE / "data_fundamental" / "name_hist.csv", dtype={"code": str}).sort_values("TRADE_DATE").groupby("code").tail(1)
NAMES = _nh.set_index("code")["SECURITY_NAME_ABBR"].astype(str).to_dict()

# ---- 加载池（复用生产过滤）----
pool = {}
for f in sorted((BASE / "data_full").glob("*.csv")):
    code = f.stem
    if not A5.is_pool_code(code):
        continue
    if A5.is_st_name(NAMES.get(code[2:], "")):
        continue
    try:
        df = pd.read_csv(f, dtype={"date": str})
        if len(df) < 70: continue
        df = df.sort_values("date").reset_index(drop=True)
        pool[code] = df
    except Exception:
        continue
LAST = max(df["date"].iloc[-1] for df in pool.values())
log(f"池: {len(pool)} 只 | 数据截至 {LAST}")

# ---- 扫描最新交易日候选（T = LAST）：昨日涨停 ∧ 今日 gap ∧ rp ----
cands = []
for code, df in pool.items():
    if df["date"].iloc[-1] != LAST: continue
    feat = A5.compute_features(df, code)
    i = len(df) - 1
    if i < 60: continue
    if not feat["is_zt"][i - 1]: continue                     # 昨日涨停
    pc = feat["prev_close"][i]
    if not np.isfinite(pc) or pc <= 0: continue
    gap = df["open"].iloc[i] / pc - 1
    if not (GAP[0] < gap < GAP[1]): continue                   # 低开区间
    rp = feat["rel_pos"][i]
    if not np.isfinite(rp) or rp > RP_MAX: continue            # 相对位置
    cands.append(dict(code=code, name=NAMES.get(code[2:], ""), gap=float(gap), rp=float(rp),
                      open=float(df["open"].iloc[i]), close=float(df["close"].iloc[i])))
log(f"当日候选（{LAST}）: {len(cands)} 只")
for c in cands:
    log(f"  {c['code']} {c['name']} gap={c['gap']*100:+.2f}% rp={c['rp']:.2f} 开={c['open']:.2f}")

# ---- state: 逐笔影子账本 ----
if STATE.exists():
    st = json.load(open(STATE, encoding="utf-8"))
else:
    st = dict(created=LAST, trades=[], nav=1.0, history=[])

# 对 pending（此前候选尚未平仓）检查出场：用各股最新数据（简化：按 tp_t2 在 entry 后 T+1/T+2 判定）
still_pending = []
for p in st.get("pending", []):
    code = p["code"]
    df = pool.get(code)
    if df is None: continue
    idx = df.index[df["date"] >= p["entry_date"]].tolist()
    if not idx: continue
    eb = idx[0]  # entry bar
    feat = A5.compute_features(df, code)
    T, px, why = A5.apply_tp_t2(df, feat, eb, p["entry_px"])
    if T <= len(df) - 1:
        ret = (px / p["entry_px"] - 1) - 0.0115  # 往返成本
        st["trades"].append(dict(code=code, entry_date=p["entry_date"], exit_date=df["date"].iloc[T],
                                 entry_px=p["entry_px"], exit_px=float(px), why=why, ret=float(ret)))
        st["nav"] = float(np.prod([1 + t["ret"] for t in st["trades"]]))
    else:
        still_pending.append(p)

# 今日候选入 pending（T+1 == 下一交易日开盘执行；此处按"今日开盘"口径近似=当日候选当日开盘买）
for c in cands:
    if any(p["code"] == c["code"] for p in still_pending): continue
    still_pending.append(dict(code=c["code"], entry_date=LAST, entry_px=c["open"]))
st["pending"] = still_pending
st["history"].append(dict(date=LAST, n_cand=len(cands), codes=[c["code"] for c in cands]))
st["last_run"] = LAST
json.dump(st, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
log(f"账本: 累计交易 {len(st['trades'])} 笔 | 影子净值 {st['nav']:.4f} | pending {len(st['pending'])}")
log("状态:", str(STATE))
log("A5 PAPER OK")
