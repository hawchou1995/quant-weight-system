# -*- coding: utf-8 -*-
"""影子轨 shadow_ret20（2026-09-17 建）——ret20 倾斜候选的纸面跟踪（用户拍板 ③）

拍板（2026-09-17）：生产 composite 完全不动；影子轨记录三臂：
  BASE = 生产 13 因子复合分（研究冻结引擎 composite()）
  L02  = (zclip(comp) + 0.2·zclip(ret20)) / 1.2      ← 主候选
  L03  = (zclip(comp) + 0.3·zclip(ret20)) / 1.3      ← 陪跑对照
机制：与研究验收同一口径——冻结引擎 run_engine(臂, 20, offset=0) 全窗口重跑，
      取影子起点之后的段做归一化净值；双成本档（20bp 基准 / 50bp 压力）。
产出：
  backtest/shadow_ret20/ledger.csv          日度净值（归一化，起点=1.0）+ 原始权益
  backtest/shadow_ret20/daily_metrics.jsonl 日度：TopN 重叠/换手/行业暴露/风格暴露/三臂名单
  backtest/shadow_ret20/state.json          起点、口径、引擎锚
用法：python backtest/shadow_ret20.py    # 挂在 rebuild_panels 之后、build_satellite_pool 之前
验收（用户定）：≥1-3 个月；BASE/L02/L03 月度相对稳定性（多数月份为正）；相对回撤不失控。
"""
import importlib.util, numpy as np, pandas as pd, json, time, os, gc, sys
np.seterr(all="ignore")
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)
HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
OUT = os.path.join(HERE, "shadow_ret20")
os.makedirs(OUT, exist_ok=True)
LEDGER = os.path.join(OUT, "ledger.csv")
METRICS = os.path.join(OUT, "daily_metrics.jsonl")
STATE = os.path.join(OUT, "state.json")
# ---------- 加载冻结引擎（与研究口径同源；软锚——数据版本日更，22.87 为历史锚非硬门）----------
_src = open(os.path.join(HERE, "oss_0913", "oss_super_combo_0913.py"), encoding="utf-8").read()
G = {}
exec(_src.split("comp = composite()")[0], G)
ND, NC = G["ND"], G["NC"]
cal = [str(d)[:10] for d in G["cal"]]
close_ff = G["close_ff"]; EL = G["ELIG3"]
rB = G["run_engine"](G["composite"](), 20, offset=0)
annB = float(rB["ann"]) * 100
drift = abs(annB - 22.87)
log(f"[锚] 冻结引擎 off0 年化 {annB:.2f}%（历史锚 22.87% | 漂移 {drift:.2f}pp — 面板已延展，漂移<1.5pp 视为正常）")
if drift > 3.0:
    log(f"[ABORT] 引擎锚漂移 {drift:.2f}pp > 3.0pp——面板/因子疑似异常，拒绝出数")
    sys.exit(1)
elif drift > 1.0:
    log(f"[WARN] 锚漂移 {drift:.2f}pp（数据版本推进所致，正常范围；>3pp 才中止）")
# ---------- 三臂 ----------
comp = G["composite"]()
ret20 = close_ff / pd.DataFrame(close_ff).shift(20).to_numpy() - 1
def zclip(sig):
    a = np.where(EL & np.isfinite(sig), sig, np.nan)
    mu = np.nanmean(a, axis=1, keepdims=True); sd = np.nanstd(a, axis=1, keepdims=True)
    z = np.clip((a - mu) / (sd + 1e-12), -3, 3)
    return np.where(np.isfinite(z), z, np.nan)
z_comp = zclip(comp); z_ret = zclip(ret20)
def blend(lam):
    zb = (z_comp + lam * z_ret) / (1 + lam)
    return np.where(np.isfinite(z_comp) & np.isfinite(z_ret), zb, np.where(np.isfinite(z_comp), z_comp, np.nan))
ARMS = {"base": comp, "l02": blend(0.2), "l03": blend(0.3)}
RES = {}
for name, comp_ in ARMS.items():
    r0 = G["run_engine"](comp_, 20, offset=0)
    r50 = G["run_engine"](comp_, 20, offset=0, slip=0.0050)
    RES[name] = {
        "eq": pd.Series(r0["equity"]).pct_change().fillna(0).add(1).cumprod(),
        "eq50": pd.Series(r50["equity"]).pct_change().fillna(0).add(1).cumprod(),
        "n_trades": int(r0["n_trades"]),
    }
    log(f"[{name}] 全窗 off0 年化 {float(r0['ann'])*100:+.2f}% | 笔 {int(r0['n_trades'])}")
last_date = cal[-1]
# ---------- 起点与归一 ----------
start_date = None
if os.path.exists(STATE):
    start_date = json.load(open(STATE, encoding="utf-8")).get("start_date")
if start_date is None:
    start_date = last_date
    json.dump({"start_date": start_date, "spec": {"base": "冻结引擎 composite()（13 因子 ICIR 复合）",
               "l02": "(z(comp)+0.2·z(ret20))/1.2", "l03": "(z(comp)+0.3·z(ret20))/1.3",
               "engine": "run_engine(arm, 20, offset=0)；成本=引擎内建（20bp 基准档 / 50bp 压力档）",
               "decision": "2026-09-17 用户拍板 ③纸面跟踪；生产 composite 不动"},
              "created": time.strftime("%Y-%m-%d %H:%M")},
              open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log(f"[起点] 影子起点 = {start_date}")
def nav_since(sr):
    eq = sr[sr.index.map(lambda d: str(d)[:10] >= start_date)]
    if len(eq) == 0: return None
    return eq / eq.iloc[0]
row = {"date": last_date}
for name in ARMS:
    for col, key in (("nav_", "eq"), ("nav50_", "eq50")):
        s = nav_since(RES[name][key])
        row[col + name] = round(float(s.iloc[-1]), 6) if s is not None else None
    row["raw_base" if name == "base" else f"raw_{name}"] = round(float(RES[name]["eq"].iloc[-1]), 4)
# ---------- 写 ledger（同日去重）----------
led = pd.read_csv(LEDGER) if os.path.exists(LEDGER) else pd.DataFrame()
if len(led) and str(led["date"].iloc[-1]) == last_date:
    led = led.iloc[:-1]
led = pd.concat([led, pd.DataFrame([row])], ignore_index=True)
led.to_csv(LEDGER, index=False, encoding="utf-8-sig")
# ---------- 日度指标 ----------
def top20(comp_):
    di = ND - 1
    sc = comp_[di]
    ok = np.where(np.isfinite(sc) & EL[di])[0]
    ok = sorted(ok, key=lambda j: -sc[j])
    # 剔 ST/退（生产口径，2026-09-17 修：原仅剔"退"；现与 build_satellite_pool.py 同源）
    out = []
    for j in ok:
        c = str(G["codes"][j])[-6:]
        if c in ST_SET or c in TUI_SET:
            continue
        if not (ST_SET or TUI_SET) and ("ST" in NAMES.get(c, "") or "退" in NAMES.get(c, "")):
            continue                                   # 回退：name_hist 不可用时按名字串匹配
        out.append(c)
        if len(out) >= 20: break
    return out
try:
    NAMES = json.load(open(os.path.join(BASE, "data_full_names.json"), encoding="utf-8"))
    _n2 = {}
    for k, v in NAMES.items():
        _n2[str(k)[-6:]] = v
    NAMES = _n2
except Exception:
    NAMES = {}
# ST/退 集合（生产口径：data_fundamental/name_hist.csv 每票最新名，与 build_satellite_pool.py 同源）
try:
    _nh = pd.read_csv(os.path.join(BASE, "data_fundamental", "name_hist.csv"),
                      dtype={"code": str}).sort_values("TRADE_DATE").groupby("code").tail(1)
    _nm = _nh.set_index("code")["SECURITY_NAME_ABBR"].astype(str)
    _nm.index = [str(i)[-6:] for i in _nm.index]
    TUI_SET = set(_nm[_nm.str.contains("退")].index)
    ST_SET = set(_nm[_nm.str.contains("ST")].index)
    log(f"[ST/退] name_hist 最新名：ST {len(ST_SET)} 只 / 退 {len(TUI_SET)} 只（生产同源过滤）")
except Exception as _e:
    TUI_SET, ST_SET = set(), set()
    log(f"[ST/退] name_hist 不可用（{type(_e).__name__}）→ 回退名字串匹配")
try:
    IND = json.load(open(os.path.join(BASE, "stock_industry.json"), encoding="utf-8"))["map"]
except Exception:
    IND = {}
lists = {name: top20(ARMS[name]) for name in ARMS}
prev_lists = None
if os.path.exists(METRICS):
    for ln in open(METRICS, encoding="utf-8").read().strip().splitlines()[-1:]:
        try: prev_lists = json.loads(ln).get("lists")
        except Exception: prev_lists = None
def overlap(a, b):
    return round(len(set(a) & set(b)) / max(1, len(set(a) | set(b))), 3)
def turnover(a, b):
    if not b: return None
    return round(1 - len(set(a) & set(b)) / max(1, len(a)), 3)
def industry_expo(codes):
    w = {}
    for c in codes:
        k = IND.get(str(c)[-6:], "—")
        w[k] = round(w.get(k, 0) + 1 / len(codes), 3)
    return dict(sorted(w.items(), key=lambda x: -x[1])[:6])
di = ND - 1
zr_row = z_ret[di]
code2j = {str(c)[-6:]: j for j, c in enumerate(G["codes"])}
def _mz(codes):
    vals = [zr_row[code2j[c]] for c in codes if c in code2j and np.isfinite(zr_row[code2j[c]])]
    return round(float(np.mean(vals)), 3) if vals else None
met = {
    "date": last_date, "start": start_date,
    "overlap": {"l02_vs_base": overlap(lists["l02"], lists["base"]), "l03_vs_base": overlap(lists["l03"], lists["base"]),
                "l02_vs_l03": overlap(lists["l02"], lists["l03"])},
    "turnover": {name: turnover(lists[name], (prev_lists or {}).get(name)) for name in ARMS},
    "industry": {name: industry_expo(lists[name]) for name in ARMS},
    "style_mean_ret20_z": {name: _mz(lists[name]) for name in ARMS},
    "nav": {name: row["nav_" + name] for name in ARMS},
    "lists": lists,
}
_lines = open(METRICS, encoding="utf-8").read().strip().splitlines() if os.path.exists(METRICS) else []
_keep = []
for _ln in _lines:
    try:
        if json.loads(_ln).get("date") != last_date: _keep.append(_ln)
    except Exception: pass
_lines = _keep
with open(METRICS, "w", encoding="utf-8") as fh:
    if _lines: fh.write("\n".join(_lines) + "\n")
    fh.write(json.dumps(met, ensure_ascii=False) + "\n")
# 引擎锚文件（供研究侧 load_engine 自维护对齐；日链每次运行刷新）
json.dump({"base_off0_ann": round(annB, 3), "asof": last_date, "historical": 22.87,
           "note": "冻结引擎 BASE 臂 off0 年化（当前数据版本）；研究侧 load_engine 读此文件做对齐检查"},
          open(os.path.join(HERE, "engine_anchor.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
# ---------- 摘要 ----------
def mdd(srs):
    if srs is None or len(srs) < 2: return None
    return round(float((srs / srs.cummax() - 1).min()) * 100, 2)
log(f"[影子] 起点 {start_date} → 最新 {last_date}")
for name in ARMS:
    s = nav_since(RES[name]["eq"]); s50 = nav_since(RES[name]["eq50"])
    log(f"  {name:4s} NAV {float(s.iloc[-1]):.4f}（50bp {float(s50.iloc[-1]):.4f}）| 窗口内 MaxDD {mdd(s)}% | 名单 {len(lists[name])} 只")
log(f"  L02−BASE 差 {float(nav_since(RES['l02']['eq']).iloc[-1]) - float(nav_since(RES['base']['eq']).iloc[-1]):+.4f} | TopN 重叠 {met['overlap']}")
log(f"[落盘] {LEDGER} / {METRICS}")
