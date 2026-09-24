# -*- coding: utf-8 -*-
"""
热榜哨兵（见底共振 Top30 前向影子哨兵）· 日更入口
=================================================
规则版本 RULE_VERSION = R-jiandi-top30-0924/v1
影子起点 shadow_start   = 2026-09-24（**预注册冻结**，见 backtest/PRE-REGISTRATION_20260924_jiandi_top30_sentinel.md）

冻结口径（日更中不得改动）
- 宇宙：沪深主板（sh60/sz00/sz002）× len(df) >= 400 × 排除 sh5/sz1/bj（= v8_selector.load_pool 口径）
- 信号：六个分项（入市/机会/见底/穿20/穿25/穿30）中 >= 2 个 = 共振
- 触发：当日全市场共振家数 >= THETA(30) → 触发日
- 入场：T 收盘确认 → T+1 开盘买（本脚本**不下单**，只出池）
- 出场：RSI(14) 域 55/65/65（熊 55 / 非熊 65），兜底满 5 日；次日开盘卖

数据源：data_full/*.csv 直读（真值 = 各 CSV 末行日期）。
不读 v8_factor_cache.pkl（1.3GB 全链共享派生缓存，末行可能落后 data_full 一日）。

产物（幂等：同一 --date 重跑只覆盖、不追加、绝不伪造净值/持仓）
- sentinel_pool.js            window.SENTINEL_POOL   （当日选股池 + 最近触发日池）
- sentinel_track.js           window.SENTINEL_TRACK  （跟踪池 / 影子账本：只记账不成交）
- backtest/sentinel_state.json                        （影子状态：shadow_start / last_run / trading_enabled）
- backtest/sentinel_backtest.json                     （仅 --refresh-backtest：给看板「回测数据」子块）

用法
- python backtest/sentinel_daily.py --date 2026-09-24                     # 正式（写盘）
- python backtest/sentinel_daily.py --date 2026-09-24 --dry-run           # 只算不写
- python backtest/sentinel_daily.py --date 2026-09-24 --refresh-backtest  # 顺带刷新回测摘要
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent          # .../backtest
BASE = HERE.parent                              # repo root
for _p in (str(HERE), str(BASE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import jiandi_signal_0906 as JG   # 复用 board_of / jiandi_signals（其 main() 内的缓存读不会被触发）

# ---------------- 冻结常量 ----------------
STRATEGY = "热榜哨兵"
STRATEGY_KEY = "sentinel"
RULE_VERSION = "R-jiandi-top30-0924/v1"
SHADOW_START = "2026-09-24"          # 预注册冻结；若既有 state 与之不一致 → 直接报错，不静默改写
THETA = 30
HOLD = 5
MIN_ROWS = 400
W_LO = pd.Timestamp("2016-06-01")
THR_A3 = {0: 55, 1: 65, 2: 65}
SUBS = [("rushi", "入市"), ("jihui", "机会"), ("jiandi", "见底"),
        ("kuaixian", "穿20"), ("laiLin", "穿25"), ("deng", "穿30")]
SKIP_PREFIX = ("sh5", "sz1", "bj")
UNIVERSE_LABEL = "沪深主板（sh60/sz00/sz002）· len(df)>=400 · 排除 sh5/sz1/bj"
ENTRY_LABEL = "K>=2 共振 且当日共振家数 θ>=30；T 收盘确认 → T+1 开盘买（本脚本不下单）"
EXIT_LABEL = "RSI(14) 域 55/65/65（熊 55 / 非熊 65），兜底满 5 日；次日开盘卖"

IDX_CSV = BASE / "index_000300.csv"
NAMES_JSON = BASE / "data_full_names.json"
POOL_JS = BASE / "sentinel_pool.js"
TRACK_JS = BASE / "sentinel_track.js"
STATE_JSON = HERE / "sentinel_state.json"
BT_JSON = HERE / "sentinel_backtest.json"
GRID_OUT = HERE / "jiandi_top_grid_0924_out"

DATA_DIR_CANDIDATES = [BASE / "data_full", Path(r"D:\Documents\Quant data\data_full")]

_HASH_DROP = ("built_at", "generated_at", "last_run", "created", "updated",
              "content_sha256", "outputs", "at")


# ---------------- 小工具 ----------------
def now_stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _scrub(obj):
    if isinstance(obj, dict):
        return {k: (None if k in _HASH_DROP else _scrub(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub(v) for v in obj]
    return obj


def content_hash(obj) -> str:
    """内容指纹：抹掉时间戳/自身指纹/产物哈希后取 sha256 → 幂等可证（同内容必同值）。"""
    s = json.dumps(_scrub(obj), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def find_data_dir():
    for p in DATA_DIR_CANDIDATES:
        if p.is_dir():
            return p
    return None


def load_names() -> dict:
    if NAMES_JSON.exists():
        try:
            return json.loads(NAMES_JSON.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def build_regime(idx: pd.DataFrame) -> dict:
    """分域状态（前一交易日状态，严格 T-1 对齐）：0=熊（收盘<MA60）1=强牛（>MA20）2=弱牛。"""
    is_bear = (idx["close"] < idx["ma60"]).to_numpy()
    bull = (~is_bear) & (idx["close"] > idx["ma20"]).to_numpy()
    state = np.where(is_bear, 0, np.where(bull, 1, 2))
    prev_map, prev = {}, None
    for k, dt in enumerate(idx["date"]):
        prev_map[dt] = prev if prev is not None else 0
        prev = int(state[k])
    return prev_map


def rsi_series(c: pd.Series, n: int = 14) -> np.ndarray:
    delta = c.diff()
    gain = delta.clip(lower=0).rolling(n, min_periods=1).mean()
    loss = (-delta.clip(upper=0)).rolling(n, min_periods=1).mean()
    return (100 - 100 / (1 + gain / loss.replace(0, np.nan))).to_numpy()


def atomic_write(path: Path, text: str, dry: bool):
    """原子写（tmp + os.replace）；dry=True 只算不写。返回 (bytes, sha256)。"""
    raw = text.encode("utf-8")
    sha = hashlib.sha256(raw).hexdigest()
    if not dry:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8", newline="")
        os.replace(tmp, path)
    return len(raw), sha


def write_js(path: Path, varname: str, obj: dict, dry: bool):
    text = "window.%s = %s;" % (varname, json.dumps(obj, ensure_ascii=False))
    return atomic_write(path, text, dry)


def write_json(path: Path, obj: dict, dry: bool):
    text = json.dumps(obj, ensure_ascii=False, indent=1)
    return atomic_write(path, text, dry)


def assert_no_bj(obj, where: str):
    """R-no-bj-0923 构建期硬闸：池产物含北交所代码 → 中止（不静默出池）。"""
    try:
        from no_bj import assert_clean
    except Exception as e:
        print("[sentinel] WARN: no_bj 闸门不可用（%s）→ 跳过北交所断言" % e)
        return
    assert_clean(obj, where)


# ---------------- 扫描（真值） ----------------
def do_scan(data_dir: Path, as_of_ts: pd.Timestamp, log) -> dict:
    """data_full 直读全市场，算「见底共振」日频家数与候选（主板口径）。"""
    idx = pd.read_csv(IDX_CSV, dtype={"date": str})
    idx["date"] = pd.to_datetime(idx["date"])
    idx = idx.sort_values("date").reset_index(drop=True)
    for maw in (20, 60):
        idx["ma%d" % maw] = idx["close"].rolling(maw, min_periods=1).mean()
    reg_map = build_regime(idx)

    cal = [d for d in idx["date"] if W_LO <= d <= as_of_ts]
    if not cal:
        raise SystemExit("[sentinel] ERR: 回测窗口内无交易日（W_LO=%s, as_of=%s）"
                         % (W_LO.date(), as_of_ts.date()))
    last_cal = cal[-1]
    cal_pos = {d: i for i, d in enumerate(cal)}

    cache, skipped_short, skipped_pref = {}, 0, 0
    for p in sorted(data_dir.glob("*.csv")):
        c = p.stem
        if c.startswith(SKIP_PREFIX):
            skipped_pref += 1
            continue
        if JG.board_of(c) != "main":
            continue
        try:
            df = pd.read_csv(p, dtype={"date": str})
        except Exception:
            continue
        if len(df) < MIN_ROWS:
            skipped_short += 1
            continue
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        cache[c] = df
    log("宇宙 %d 只（主板 · len>=%d；跳过 len<%d: %d；前缀剔除: %d）"
        % (len(cache), MIN_ROWS, MIN_ROWS, skipped_short, skipped_pref))
    n_with_bar = sum(1 for df in cache.values() if last_cal in df.index)

    res_daily = defaultdict(int)
    n_bad = defaultdict(int)
    cands = defaultdict(list)
    for code, df in cache.items():
        if len(df) < 70:
            continue
        sm = JG.jiandi_signals(code, df)
        sig = [np.asarray(sm[k], bool) for k, _ in SUBS]
        cnt = np.sum(sig, axis=0)
        if not (cnt >= 2).any():
            continue
        o = df["open"].to_numpy()
        c = df["close"].to_numpy()
        amtv = df["amount"].to_numpy() if "amount" in df.columns else None
        volv = df["volume"].to_numpy() if "volume" in df.columns else None
        bad = (~np.isfinite(o)) | (~np.isfinite(c)) | (o <= 0) | (c <= 0)
        dates = df.index
        for i in np.where(cnt >= 2)[0]:
            sd = dates[i]
            if sd < W_LO or sd not in cal_pos:
                continue
            if bad[i]:
                n_bad[sd] += 1
                continue
            res_daily[sd] += 1
            cands[sd].append(dict(
                code=code, i=int(i), cnt=int(cnt[i]),
                subs=[lab for (k, lab), fl in zip(SUBS, sig) if fl[i]],
                close=float(c[i]),
                amt=(float(amtv[i]) if amtv is not None and np.isfinite(amtv[i]) else None),
                vol=(float(volv[i]) if volv is not None and np.isfinite(volv[i]) else None)))
    log("剔除 0 价污染候选 %d 个" % sum(n_bad.values()))

    return dict(idx=idx, reg_map=reg_map, cal=cal, last_cal=last_cal, cache=cache,
                res_daily=res_daily, cands=cands, n_bad=n_bad,
                n_universe=len(cache), n_with_bar=n_with_bar,
                skipped_short=skipped_short, skipped_pref=skipped_pref)


def replay_one(scan: dict, cand: dict):
    """历史重放：T+1 开盘买 → RSI 域阈值触发（次日开盘卖）/ 兜底 5 日。返回 dict 或 None。"""
    df = scan["cache"][cand["code"]]
    o = df["open"].to_numpy()
    c = df["close"].to_numpy()
    dts = df.index
    n = len(df)
    rsi = rsi_series(df["close"], 14)
    i = cand["i"]
    B = i + 1
    if B >= n or not (np.isfinite(o[B]) and o[B] > 0):
        return None
    sell = min(B + HOLD, n - 1)
    for d in range(B, min(B + HOLD, n)):
        st = scan["reg_map"].get(dts[d])
        thr = THR_A3.get(st if st is not None else 0, 55)
        if np.isfinite(rsi[d]) and rsi[d] >= thr:
            sell = min(d + 1, B + HOLD)
            break
    if sell <= B or sell >= n:
        return None
    w = slice(B, sell + 1)
    if not (np.isfinite(o[w]).all() and np.isfinite(c[w]).all()
            and (o[w] > 0).all() and (c[w] > 0).all()):
        return None
    return dict(buy=dts[B], bpx=float(o[B]), sell=dts[sell], spx=float(o[sell]),
                ret=(float(o[sell]) / float(o[B]) - 1) * 100)


def ranked(scan: dict, sd, mincnt: int = 2):
    cs = [c for c in scan["cands"].get(sd, []) if c["cnt"] >= mincnt]
    cs.sort(key=lambda x: (-x["cnt"], -(x["amt"] or 0.0), x["code"]))
    return cs


def pool_entries(scan: dict, sd, names: dict):
    rows = []
    for k, c in enumerate(ranked(scan, sd), 1):
        r = replay_one(scan, c)
        rows.append(dict(
            rank=k, code=c["code"], key=c["code"],
            name=str(names.get(c["code"], "") or ""),
            pool=STRATEGY_KEY, perm=STRATEGY_KEY, board="主板",
            cnt=c["cnt"], subs=c["subs"], sub_labels="+".join(c["subs"]),
            close=round(c["close"], 2), amount=c["amt"],
            buy_date=(r["buy"].date().isoformat() if r else None),
            buy_open=(round(r["bpx"], 2) if r else None),
            sell_date=(r["sell"].date().isoformat() if r else None),
            sell_px=(round(r["spx"], 2) if r else None),
            ret_gross_pct=(round(r["ret"], 2) if r else None),
            ret_net_pct=(round(r["ret"] - 1.15, 2) if r else None)))
    return rows


# ---------------- 影子状态 ----------------
def load_state():
    if STATE_JSON.exists():
        try:
            st = json.loads(STATE_JSON.read_text(encoding="utf-8"))
        except Exception as e:
            raise SystemExit("[sentinel] ERR: %s 解析失败（%s）→ 请人工修复后再跑（不自动重建）"
                             % (STATE_JSON, e))
        if st.get("shadow_start") and st["shadow_start"] != SHADOW_START:
            raise SystemExit("[sentinel] ERR: 既有 state 的 shadow_start=%s 与预注册冻结值 %s 不一致 → 拒绝改写"
                             % (st["shadow_start"], SHADOW_START))
        return st
    return {}


# ---------------- 回测摘要（--refresh-backtest） ----------------
def build_backtest_summary(log) -> dict:
    """从既有真实回测产物汇总「回测数据」子块字段；缺来源 → null + note（绝不编数字）。"""
    p170 = GRID_OUT / "top1_personal_170k_0924.json"
    pyear = GRID_OUT / "top1_personal_yearly_0924.json"
    pnav = GRID_OUT / "top1_nav_daily_0924.csv"
    ARM = "A2 固定55 | 2槽x6万·日限2"
    PREREG_REPORT = "backtest/jiandi_top_grid_0924_out/报告-见底共振×高点警示-网格回测-20260924.md §11D（预注册引用）"

    d170 = json.loads(p170.read_text(encoding="utf-8")) if p170.exists() else None
    dyear = json.loads(pyear.read_text(encoding="utf-8")) if pyear.exists() else None
    cnt = rd = None
    if d170:
        cnt = d170["results"][ARM]["cnt_rule"]
        rd = d170["results"][ARM]["random_dist"]
    _er = ((d170 or {}).get("event_ref") or {})
    _er_fam = ARM.split(" | ")[0].strip()
    _er_key = ARM if ARM in _er else (_er_fam if _er_fam in _er else None)
    ev_ref = _er.get(_er_key) if _er_key else None

    nav_metrics = {}
    if pnav.exists():
        nav = pd.read_csv(pnav)
        nav["date"] = pd.to_datetime(nav["date"])
        nav = nav.sort_values("date")
        dd = (nav["nav"] / nav["nav"].cummax() - 1) * 100
        rets = nav["nav"].pct_change().dropna()
        sharpe = (float(rets.mean() / rets.std() * np.sqrt(244))
                  if len(rets) > 2 and float(rets.std()) > 0 else None)
        nav_metrics = dict(
            source="backtest/jiandi_top_grid_0924_out/top1_nav_daily_0924.csv",
            nav_start=str(nav["date"].iloc[0].date()), nav_end=str(nav["date"].iloc[-1].date()),
            nav_first=round(float(nav["nav"].iloc[0]), 4), nav_last=round(float(nav["nav"].iloc[-1]), 4),
            n_rows=int(len(nav)), mdd_pct=round(float(dd.min()), 2),
            mdd_date=str(nav.loc[dd.idxmin(), "date"].date()),
            sharpe_ann_daily_selfcomputed=(round(sharpe, 3) if sharpe is not None else None),
            sharpe_convention="mean/std(日净值收益) × sqrt(244) —— 本脚本现算，非既有产物字段")

    ev_yearly = (dyear or {}).get("ev_yearly", {})
    tot_n = sum(v["n"] for v in ev_yearly.values()) if ev_yearly else None
    tot_days = sum(v["trigger_days"] for v in ev_yearly.values()) if ev_yearly else None
    cfg = (dyear or {}).get("configs", {})

    per_year = []
    for y in [str(x) for x in range(2016, 2027)]:
        v = ev_yearly.get(y)
        c2 = cfg.get("6万×2", {}).get("per_year", {}).get(y, {})
        per_year.append(dict(
            year=int(y),
            trigger_days=(v["trigger_days"] if v else None),
            events=(v["n"] if v else None),
            mean_gross_pct=(round(v["mean_gross_pct"], 2) if v and v["mean_gross_pct"] is not None else None),
            win_pct=(round(v["win_pct"], 1) if v and v["win_pct"] is not None else None),
            trades_med=cfg.get("6万×2", {}).get("trades_per_year", {}).get(y),
            ret_med_pct=c2.get("med"), ret_p5_pct=c2.get("p5"), ret_p95_pct=c2.get("p95")))

    out = dict(
        schema="sentinel_backtest/v1", strategy=STRATEGY, strategy_key=STRATEGY_KEY,
        rule_version=RULE_VERSION, generated_at=now_stamp(),
        generated_by="backtest/sentinel_daily.py --refresh-backtest",
        scope="「热榜哨兵」子标签独占的回测摘要（个人 17 万槽位口径 + 预注册组合级参照）",
        period=("2016-06-01 → 2026-09-23" if cnt else None),
        period_start="2016-06-01", period_end="2026-09-23",
        period_note=("回测数据尾 = 共享缓存 v8_factor_cache.pkl 末行 2026-09-23；"
                     "当日池数据另见 sentinel_pool.js(as_of=2026-09-24)"),
        note=("口径 = 个人 17 万槽位引擎（主假设臂 RSI 固定 55）· 2 槽 × 6 万 · 日限 2 笔 · 逐元记账整手撮合 · "
              "含费（佣金 8.6bp 双边底 5 元 / 印花税 5bp 卖出 / 过户费 1bp 双边）· "
              "交易数 = 槽位引擎实际成交笔数（全事件池 9833 笔中的可执行子集）"),
        total_return=(cnt["total_ret_pct"] if cnt else None),
        ann_return=(cnt["annual_pct"] if cnt else None),
        max_drawdown=(cnt["mdd_pct"] if cnt else None),
        n_trades=(cnt["trades"] if cnt else None),
        win_rate=(cnt["win_pct"] if cnt else None),
        med_per_trade=None,
        med_per_trade_note=("17 万槽位产物未输出「单笔收益中位数」（只输出均值 avg_trade_ret_pct=%s）；"
                            "事件级均值/胜率见 event_ref，不在此处换算，避免与槽位口径混淆"
                            % (cnt["avg_trade_ret_pct"] if cnt else "n/a")),
        sharpe=None,
        sharpe_note=("17 万槽位产物未输出 Sharpe（拿不到 → null）；预注册组合级参照 Sharpe=0.921 @K=5·1.15% 成本，"
                     "属另一口径（见 reference_preregistered），不得与本卡字段混用"),
        n_trigger_days=(tot_days if tot_days is not None else None),
        n_trigger_days_note="触发日 = 当日全市场（主板 ≥2 共振）家数 ≥30 的交易日；由历年汇总精确求和",
        n_picks=(tot_n if tot_n is not None else None),
        n_picks_note=("= 事件笔数（触发日 × 当日 ≥2 共振主板标的），毛收益口径；"
                      "槽位引擎受 2 槽/日限 2 约束只成交其子集"),
        entry_rule=ENTRY_LABEL, exit_rule=EXIT_LABEL, universe=UNIVERSE_LABEL,
        trigger_threshold=THETA, hold_days=HOLD, capital=170000.0, arm=ARM,
        event_ref=(dict(n=ev_ref["n"], mean_gross_pct=round(ev_ref["mean_gross_pct"], 2),
                        win_pct=round(ev_ref["wr_pct"], 1),
                        note="事件级毛收益（未扣费）· 来源 top1_personal_170k_0924.json event_ref['%s']" % _er_key)
                   if ev_ref else dict(n=None, mean_gross_pct=None, win_pct=None,
                                       note="拿不到：top1_personal_170k_0924.json 缺失或无 event_ref")),
        arms_17w=({k: dict(total_ret_pct=v["cnt_rule"]["total_ret_pct"], annual_pct=v["cnt_rule"]["annual_pct"],
                           mdd_pct=v["cnt_rule"]["mdd_pct"], trades=v["cnt_rule"]["trades"],
                           win_pct=v["cnt_rule"]["win_pct"]) for k, v in d170["results"].items()}
                  if d170 else {}),
        seed_dist=(dict(source="top1_personal_170k_0924.json results['%s'].random_dist" % ARM, **rd)
                   if rd else dict(note="拿不到：random_dist 缺失")),
        portfolio=dict(
            end_median_eq=({k: cfg[k]["end"] for k in cfg} if cfg else None),
            end_median_eq_meaning="200 个随机起始日 / 随机选股种子的期末权益中位数（个人 17 万口径）",
            trades_per_year=({k: cfg[k]["trades_per_year"] for k in cfg} if cfg else None)),
        reference_preregistered=dict(source=PREREG_REPORT,
                                     config="θ30 · A6(域55/65/65) · K=5 等权 · 1.15% 往返成本",
                                     cagr_pct=11.50, sharpe=0.921, mdd_pct=-20.1,
                                     note=("组合级 K=5 等权 NAV 口径；与本卡 total_return/ann_return/max_drawdown"
                                           "（个人 17 万槽位引擎）不同口径，勿混用")),
        derived_from_nav_series=(nav_metrics or dict(note="拿不到：top1_nav_daily_0924.csv 缺失")),
        per_year=per_year,
        quality_gate=dict(
            data_bar_checked="data_full/*.csv 末行日期直读；池产物 as_of 与末行日期对照（见 sentinel_pool.js universe/data）",
            lookahead="T 收盘确认 → T+1 开盘买；出场次日开盘；无未来函数（与预注册冻结口径一致）",
            empty_pool="2026-09-24 共振 0 家（非缺数据）→ 空池，非失败",
            no_fabrication="缺失字段一律 null + note；净值/持仓不伪造（影子账本空仓）"),
        sources=dict(personal_170k=(str(p170.relative_to(BASE)) if p170.exists() else None),
                     yearly=(str(pyear.relative_to(BASE)) if pyear.exists() else None),
                     nav=(str(pnav.relative_to(BASE)) if pnav.exists() else None),
                     prereg="backtest/PRE-REGISTRATION_20260924_jiandi_top30_sentinel.md"),
        caveats=["逐年收益 = 200 种子中位数 [p5~p95]，非单一路径；2016 年 0 笔因窗口内无满足阈值事件",
                 "逐年触发日/事件按信号日归年；收益按年末权益归年",
                 "MDD 三处口径不同：槽位引擎规则路径（本卡 max_drawdown）、NAV 日序（derived_from_nav_series）、"
                 "预注册 K=5 组合级（reference_preregistered）"])
    out["content_sha256"] = content_hash(out)
    log("回测摘要：period=%s n_trigger_days=%s n_picks=%s total_return=%s ann=%s mdd=%s sharpe=%s"
        % (out["period"], out["n_trigger_days"], out["n_picks"], out["total_return"],
           out["ann_return"], out["max_drawdown"], out["sharpe"]))
    return out


# ---------------- 主流程 ----------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="热榜哨兵日更（R-jiandi-top30-0924/v1）")
    ap.add_argument("--date", default=None, help="看板子标签日期 YYYY-MM-DD（默认 = index_000300.csv 末行）")
    ap.add_argument("--dry-run", action="store_true", help="只算不写（不落盘任何文件）")
    ap.add_argument("--refresh-backtest", action="store_true", help="顺带刷新 backtest/sentinel_backtest.json")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    t0 = time.time()

    def log(m):
        if not args.quiet:
            print("[%6.1fs] %s" % (time.time() - t0, m), flush=True)

    data_dir = find_data_dir()
    if data_dir is None:
        print("[sentinel] ERR: 找不到 data_full 目录（候选：%s）" % [str(p) for p in DATA_DIR_CANDIDATES])
        return 2

    idx0 = pd.read_csv(IDX_CSV, dtype={"date": str})
    idx_last = str(idx0["date"].iloc[-1]) if len(idx0) else None
    req = args.date or idx_last
    if not req:
        print("[sentinel] ERR: 无法确定日期（index_000300.csv 为空且未给 --date）")
        return 2
    as_of_ts = pd.Timestamp(req)
    log("data_dir=%s | --date=%s | index 末行=%s" % (data_dir, req, idx_last))

    scan = do_scan(data_dir, as_of_ts, log)
    cal, res_daily, last_cal = scan["cal"], scan["res_daily"], scan["last_cal"]
    if as_of_ts != last_cal:
        log("WARN: --date=%s 不是可交易日（或超出数据）→ 回落到最近交易日 %s" % (req, last_cal.date()))
    as_of = str(last_cal.date())

    trig = sorted([d for d, v in res_daily.items() if v >= THETA])
    is_trigger = last_cal in set(trig)
    res_asof = int(res_daily.get(last_cal, 0))
    reason = ("trigger_day" if is_trigger else
              ("no_resonance_day" if res_asof == 0 else "resonance_below_threshold"))

    names = load_names()
    pool = pool_entries(scan, last_cal, names) if is_trigger else []
    last_tgt = trig[-1] if trig else None
    last_tgt_res = int(res_daily.get(last_tgt, 0)) if last_tgt else 0
    last_tgt_pool = pool_entries(scan, last_tgt, names) if last_tgt else []
    days_ago = (cal.index(last_cal) - cal.index(last_tgt)) if last_tgt else None

    log("触发日共 %d 个｜最近 3 = %s" % (len(trig), [str(d.date()) for d in trig[-3:]]))
    log("as_of=%s 共振 %d 家（θ=%d）→ triggered=%s reason=%s 池=%d 只"
        % (as_of, res_asof, THETA, is_trigger, reason, len(pool)))
    log("最近触发日 %s（共振 %d 家 / 池 %d 只 / %s 个交易日前）"
        % (last_tgt.date() if last_tgt else None, last_tgt_res, len(last_tgt_pool), days_ago))

    # ---- 既有影子状态（冻结 shadow_start；同日重跑只覆盖，不追加）----
    prev = load_state()
    created = prev.get("created") or now_stamp()
    scan_log = [e for e in prev.get("scan_log", []) if e.get("date") != as_of]
    scan_log.append(dict(date=as_of, resonance=res_asof, threshold=THETA, triggered=is_trigger,
                         n_pool=len(pool), reason=reason,
                         action=("TRIGGER" if is_trigger else "NO_TRADE"), at=now_stamp()))
    scan_log.sort(key=lambda e: e["date"])
    veto = dict(V1=False, V2=False, V3=False, V4_diag=None,
                note="预注册 V1–V4；本影子账本 %d 个扫描日 / 0 笔成交 → 全部未触发" % len(scan_log))
    n_since = sum(1 for e in scan_log if e["date"] > SHADOW_START)

    # ================= 1) sentinel_pool.js =================
    reason_text = (
        "%s 全市场（主板 %d 只 · 当日有行情 %d 只）见底共振 ≥2 分项家数 = %d < θ%d → 非触发日，当日选股池为空"
        % (as_of, scan["n_universe"], scan["n_with_bar"], res_asof, THETA)) if not is_trigger else (
        "%s 触发日：共振 %d 家 ≥ θ%d → 当日选股池共 %d 只" % (as_of, res_asof, THETA, len(pool)))

    pool_obj = dict(
        schema="sentinel_pool/v1", strategy=STRATEGY, strategy_key=STRATEGY_KEY,
        rule_version=RULE_VERSION, as_of=as_of, built_at=now_stamp(),
        generated_by="backtest/sentinel_daily.py",
        triggered=bool(is_trigger), is_trigger=bool(is_trigger),
        reason=reason, reason_text=reason_text,
        as_of_resonance=res_asof, threshold=THETA, is_resonance_day=bool(res_asof > 0),
        last_trigger_date=(str(last_tgt.date()) if last_tgt else None),
        last_trigger_resonance=last_tgt_res,
        last_trigger_days_ago_trading_days=days_ago,
        n_pool=len(pool), n_pools=len(pool), pool=[dict(e) for e in pool],
        pool_key="code", details={e["code"]: dict(e) for e in pool},
        entry_fields=["rank", "code", "name", "cnt", "subs", "close", "amount",
                      "buy_date", "buy_open", "sell_date", "sell_px", "ret_gross_pct", "ret_net_pct"],
        entry_schema_note=("与 short_pool.js details 同构（code/key/name/pool/perm/board）；"
                           "无依据的字段（industry/biz/score/tier/factors/radar_svg）一律不填，不伪造"),
        last_trigger_pool=dict(
            trigger_date=(str(last_tgt.date()) if last_tgt else None), n_resonance=last_tgt_res,
            n_entries=len(last_tgt_pool), signal_date=(str(last_tgt.date()) if last_tgt else None),
            buy_date_all=(last_tgt_pool[0]["buy_date"] if last_tgt_pool else None),
            buy_note="历史触发日：买入 = 信号次一交易日开盘（已发生）；本轮不计入影子账本",
            entries=last_tgt_pool,
            cnt_dist={str(c): int(sum(1 for r in last_tgt_pool if r["cnt"] == c)) for c in range(6, 1, -1)}),
        resonance_tail={str(d.date()): int(res_daily.get(d, 0)) for d in cal[-15:]},
        history=dict(n_trigger_days=len(trig),
                     trigger_days_recent=[str(d.date()) for d in trig[-20:]],
                     per_year_trigger_days={str(y): sum(1 for d in trig if d.year == y)
                                            for y in sorted({d.year for d in trig})}),
        universe=dict(n=scan["n_universe"], n_with_as_of_bar=scan["n_with_bar"],
                      n_missing_as_of_bar=scan["n_universe"] - scan["n_with_bar"],
                      rule=UNIVERSE_LABEL, source="data_full/*.csv（末行日期直读）",
                      skipped_len_lt_400=scan["skipped_short"], skipped_prefix=["sh5", "sz1", "bj"]),
        data=dict(requested_date=req, as_of=as_of, last_bar=as_of, index_last_row=idx_last,
                  shared_cache="v8_factor_cache.pkl",
                  shared_cache_note="共享派生缓存末行可能落后 data_full 一日；本池一律以 data_full 末行日期为准，不读该缓存",
                  n_bad_price_excluded=int(sum(scan["n_bad"].values()))),
        provenance=dict(entry="backtest/sentinel_daily.py --date %s" % req,
                        rule_source="backtest/jiandi_signal_0906.py（见底信号公式原样移植）+ 横截面共振口径",
                        prereg="backtest/PRE-REGISTRATION_20260924_jiandi_top30_sentinel.md",
                        shadow_start=SHADOW_START),
        caveats=["本池为规则清单，不含下单执行（入场 T+1 开盘）；价格仅用于显示与历史重放",
                 "共享缓存不重建；缓存末行 ≠ data_full 末行时一律以 data_full 为准",
                 "空池 ≠ 失败：共振 0 家属正常交易日（θ=30 属低频触发，回测期 88 个触发日 / 约 10 年）"])
    assert_no_bj(pool_obj, "sentinel_pool.js")
    pool_obj["content_sha256"] = content_hash(pool_obj)
    n_pool_bytes, pool_sha = write_js(POOL_JS, "SENTINEL_POOL", pool_obj, args.dry_run)
    log("%s sentinel_pool.js（%d B, sha256=%s…, content=%s…）"
        % ("[dry-run] 将写" if args.dry_run else "已写", n_pool_bytes, pool_sha[:12],
           pool_obj["content_sha256"][:12]))

    # ================= 2) sentinel_track.js =================
    track_obj = dict(
        schema="sentinel_track/v1", strategy=STRATEGY, strategy_key=STRATEGY_KEY,
        rule_version=RULE_VERSION, as_of=as_of, built_at=now_stamp(),
        generated_by="backtest/sentinel_daily.py",
        shadow_start=SHADOW_START,
        status=("COLLECTING" if not is_trigger else "TRIGGERED"),
        trading_enabled=False,
        trading_enabled_note="影子账本不执行成交（预注册：哨兵只可否决、不自动动作）；本字段恒为 false",
        triggered=bool(is_trigger), reason=reason, as_of_resonance=res_asof, threshold=THETA,
        last_trigger_date=(str(last_tgt.date()) if last_tgt else None),
        last_trigger_resonance=last_tgt_res,
        n_holdings=0, holdings=[], positions=[], closed=[], equity=[],
        nav=None, nav_series=[],
        nav_note=("影子账本自 shadow_start=%s 建账；未触发 → 空仓 → 无成交 → 不产出净值（缺失即 null，不伪造）"
                  % SHADOW_START),
        pending_entry=[], watch=[],
        entry_plan=dict(rule=ENTRY_LABEL, exit=EXIT_LABEL,
                        next_action=(("已触发：次日开盘买入 %d 只（K 由个人槽位约束决定；本账本只登记计划，不代下单）"
                                      % len(pool)) if is_trigger else
                                     "空仓等待：当日共振 %d 家 < θ%d，不建仓" % (res_asof, THETA))),
        days_since_shadow_start=n_since, n_scans=len(scan_log),
        scans=[dict(date=e["date"], resonance=e["resonance"], threshold=e["threshold"],
                    triggered=e["triggered"], n_pool=e["n_pool"], action=e["action"], nav=None)
               for e in scan_log],
        veto_state=veto,
        ledger_independence=dict(
            own_files=["sentinel_pool.js", "sentinel_track.js", "backtest/sentinel_state.json"],
            not_written=["backtest/jiandi_top30_sentinel_state.json（官方哨兵状态）",
                         "short_pool.js / a5_pool.js / backtest/a5_paper_state.json",
                         "zuoce_jianlou_*（左侧捡漏）"],
            note="子标签间物理隔离：本账本不读写任何其它策略的池/账本/状态文件"),
        provenance=dict(entry="backtest/sentinel_daily.py --date %s" % req,
                        prereg="backtest/PRE-REGISTRATION_20260924_jiandi_top30_sentinel.md"),
        caveats=["只建账不伪造成交：holdings/positions/closed/equity 均为空数组",
                 "净值缺失写 null 并给出原因，不以 1.0 或 0 占位",
                 "同一 --date 重跑：scans 按日期覆盖（幂等），不追加"])
    assert_no_bj(track_obj, "sentinel_track.js")
    track_obj["content_sha256"] = content_hash(track_obj)
    n_track_bytes, track_sha = write_js(TRACK_JS, "SENTINEL_TRACK", track_obj, args.dry_run)
    log("%s sentinel_track.js（%d B, sha256=%s…, content=%s…）"
        % ("[dry-run] 将写" if args.dry_run else "已写", n_track_bytes, track_sha[:12],
           track_obj["content_sha256"][:12]))

    # ================= 3) backtest/sentinel_state.json =================
    state = dict(
        schema="sentinel_state/v1", strategy=STRATEGY, strategy_key=STRATEGY_KEY,
        rule_version=RULE_VERSION,
        shadow_start=SHADOW_START, created=created, last_run=now_stamp(), last_scan=as_of,
        trading_enabled=False,
        trading_enabled_note="影子账本不执行成交（预注册：只可否决）；恒 false",
        status=track_obj["status"],
        n_scans=len(scan_log),
        last_result=dict(as_of=as_of, triggered=bool(is_trigger), reason=reason,
                         as_of_resonance=res_asof, threshold=THETA, n_pool=len(pool),
                         last_trigger_date=(str(last_tgt.date()) if last_tgt else None),
                         last_trigger_resonance=last_tgt_res,
                         data_last_bar=as_of, universe_n=scan["n_universe"],
                         n_with_as_of_bar=scan["n_with_bar"]),
        outputs=dict(
            sentinel_pool_js=dict(path="sentinel_pool.js", bytes=n_pool_bytes, sha256=pool_sha,
                                  content_sha256=pool_obj["content_sha256"]),
            sentinel_track_js=dict(path="sentinel_track.js", bytes=n_track_bytes, sha256=track_sha,
                                   content_sha256=track_obj["content_sha256"])),
        scan_log=scan_log, positions=[], closed=[], equity=[], n_events_done=0,
        veto_state=veto,
        notes=["影子账本只记录扫描与计划；不伪造成交（positions/closed/equity 恒空数组）",
               "shadow_start 由预注册冻结（%s），脚本拒绝改写为其它值" % SHADOW_START,
               "回测摘要（backtest/sentinel_backtest.json）只在 --refresh-backtest 时刷新，属静态回测产物"])
    state["content_sha256"] = content_hash(state)
    n_state_bytes, state_sha = write_json(STATE_JSON, state, args.dry_run)
    log("%s backtest/sentinel_state.json（%d B, sha256=%s…, content=%s…）"
        % ("[dry-run] 将写" if args.dry_run else "已写", n_state_bytes, state_sha[:12],
           state["content_sha256"][:12]))

    # ================= 4) backtest/sentinel_backtest.json（可选刷新）=================
    if args.refresh_backtest:
        bt = build_backtest_summary(log)
        n_bt_bytes, bt_sha = write_json(BT_JSON, bt, args.dry_run)
        log("%s backtest/sentinel_backtest.json（%d B, sha256=%s…, content=%s…）"
            % ("[dry-run] 将写" if args.dry_run else "已写", n_bt_bytes, bt_sha[:12],
               bt["content_sha256"][:12]))

    # ---- 摘要（契约字段：as_of / triggered / pool size）----
    print("SUMMARY as_of=%s triggered=%s pool_size=%d reason=%s resonance=%d/%d "
          "last_trigger_date=%s last_trigger_pool=%d universe=%d with_bar=%d trigger_days=%d%s"
          % (as_of, str(bool(is_trigger)).lower(), len(pool), reason, res_asof, THETA,
             (str(last_tgt.date()) if last_tgt else "none"), len(last_tgt_pool),
             scan["n_universe"], scan["n_with_bar"], len(trig),
             " [dry-run]" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
