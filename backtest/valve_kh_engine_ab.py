# -*- coding: utf-8 -*-
"""KHunter V2 尾盘阀 A/B —— 生产引擎内 A/B（R-valve-0920）
=================================================================================
动机：上一轮 V2/B0 的 3.28% 年化出自**自建简化容器**（N=5 槽×2 万固定、整手、
uniform hold25、无牛熊门、20bp 成本、按笔复利记账），与生产 KHunter 容器不可比。
本脚本把 A/B 塞进**生产引擎** khunter_port_engine_0903.py::run_khunter_port：

容器（与生产/khunter_optim2_0910 BASE 完全一致，只差阀）：
  * 信号缓存：E.build_sig_cache(v8_factor_cache, board_only='main', st_skip=True)
  * 牛熊态：O2.load_idx() + O2.state_ma250_volscale(idx, 'none')（MA250 分域，T-1）
  * PROD_KW = dict(ob=59, osl=35, gate='hybrid_wb', env='uniform', hold_max=25,
                   low_price=3.0, ob_bull=75, osl_bull=32, low_bull=None,
                   ob_weak=80, osl_weak=32, low_weak=None, hold_weak=15)
  * 每笔 = 当前 NAV/max_hold（MAX_HOLD=10，分数股无整手）；COST_BUY=COST_SELL=0.00575
  * 卖出 = RSI>分域阈值后次日开盘清仓（ob/bull/weak 分域）

四臂：gate ∈ {'hybrid_wb', 'none'} × 阀 ∈ {B0 无阀, V2 尾盘阀}

V2 阀定义（沿用上一轮口径）：信号日尾盘 14:45 相对 14:30 回落 >0.2% → 次日不买
  * 生产引擎 buys[d] 的键 d = **执行日**（开盘买），信号日在 d 的前一交易日
    （cand[i]=sig_any[i-1]，rsi1[i]=rsi[i-1]）→ 对 (code, signal_day) 取分时
  * pull = pv(code, signal_day)['p1445']/pv(...)['p1430'] - 1；pull <= -0.002 → 剔除
  * 抓取失败如实计数；主口径 fail→不买（与上一轮 pass_v2 定义一致），
    另跑 fail→买 敏感性臂（仅当有失败时）

实现方式：源码注入（与 khunter_optim2_0910.py 的 vol_scale 钩子同范式）——
  inspect.getsource(E.run_khunter_port) 后把买入循环锚点替换为带 VALVE 过滤的版本，
  exec 进 E.__dict__ 副本命名空间。两个臂共用同一份补丁源码，仅全局 VALVE 不同
  （B0=None，V2=过滤函数）→ 容器逐字节相同，只差阀。
"""
import inspect
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
BT = BASE / "backtest"
sys.path.insert(0, str(BT))

import khunter_port_engine_0903 as E            # noqa: E402
import khunter_optim2_0910 as O2                 # noqa: E402
from t293_minute_0919 import pv                  # noqa: E402

OUT = BT / "valve_kh_engine_prod.json"
PULL_THR = -0.002                                # 尾盘回落阈值：-0.2%
PROD_KW = dict(ob=59, osl=35, gate='hybrid_wb', env='uniform', hold_max=25, low_price=3.0,
               ob_bull=75, osl_bull=32, low_bull=None,
               ob_weak=80, osl_weak=32, low_weak=None, hold_weak=15)
OPTIM2_REF = {"ann": 9.9, "sharpe": 0.684, "maxdd": -20.91, "n": 329, "total": 163.39,
              "src": "khunter_timing_out/khunter_optim2_0910.json :: BASE"}

t0 = time.time()


def log(*a):
    print(f"[{time.time()-t0:7.1f}s]", *a, flush=True)


# ---------------- 1. 生产信号缓存 + 牛熊态（与 optim2 BASE 同一套）----------------
log("加载 v8_factor_cache.pkl ...")
cache = pd.read_pickle(str(BASE / "v8_factor_cache.pkl"))
log(f"cache {len(cache)} 只")
sigs = E.build_sig_cache(cache, board_only='main', st_skip=True)
log(f"主板信号缓存 {len(sigs)} 只")
idx = O2.load_idx()
sp = O2.state_ma250_volscale(idx, 'none')
log(f"牛熊态 {len(sp)} 天（is_bear 占比 {np.mean([v['is_bear'] for v in sp.values()])*100:.1f}%）")


# ---------------- 2. 复刻引擎事件流：枚举候选 (执行日d, code) → 信号日 ----------------
def collect_candidates(sigs, osl_loose):
    """与引擎 run_khunter_port 事件流构建同口径（cand∧rsi1<osl_loose → buys[d]）。
    返回 {(exec_day, code): signal_day}；信号日 = 执行日的前一交易日（该股自身序列）。"""
    pairs = {}
    for code, s in sigs.items():
        dates = s['dates']
        for i in range(len(dates)):
            dt = pd.Timestamp(dates[i])
            if dt < E.BACKTEST_START:
                continue
            if s['cand'][i] and s['rsi1'][i] < osl_loose:
                pairs[(dt, code)] = pd.Timestamp(dates[i - 1])
    return pairs


osl_loose = max(PROD_KW['osl'], PROD_KW['osl_bull']) + 5   # env_delta=5
pairs = collect_candidates(sigs, osl_loose)
log(f"候选 stock-day {len(pairs)} 个（osl_loose={osl_loose}）"
    f" / unique (code,signal_day) {len(set((c, sd) for (_, c), sd in pairs.items()))} 个")


# ---------------- 3. 分时抓取 + V2 阀映射 ----------------
def code6(code):
    return re.sub(r'^[A-Za-z]+', '', str(code))


pull_map = {}          # (code, signal_day) -> pull 或 None(失败)
fail_list = []         # [(code, date_int)]
uniq = sorted(set((code6(c), sd) for (_, c), sd in pairs.items()))
for k, (c6, sd) in enumerate(uniq):
    try:
        d = pv(c6, int(sd.strftime('%Y%m%d')))
    except Exception as e:
        d = None
        log(f"  [pv-exc] {c6} {sd.date()} {type(e).__name__} {str(e)[:60]}")
    if d is None or d.get('p1430', 0) <= 0 or d.get('p1445', 0) <= 0:
        pull_map[(c6, sd)] = None
        fail_list.append([c6, sd.strftime('%Y-%m-%d')])
    else:
        pull_map[(c6, sd)] = d['p1445'] / d['p1430'] - 1
    if (k + 1) % 100 == 0:
        log(f"  分时进度 {k+1}/{len(uniq)}（失败 {len(fail_list)}）")
log(f"分时抓取完成：{len(uniq)} 个 unique stock-day，失败 {len(fail_list)} 个")

n_fail = len(fail_list)
veto_pull, veto_fail = set(), set()
for (d, c), sd in pairs.items():
    p = pull_map.get((code6(c), sd))
    if p is None:
        veto_fail.add((d, c))
    elif p <= PULL_THR:
        veto_pull.add((d, c))
n_cand = len(pairs)
fetched = [pull_map.get((code6(c), sd)) for (_, c), sd in pairs.items()]
fetched_ok = [p for p in fetched if p is not None]
pull_sorted = np.sort(np.array(fetched_ok)) if fetched_ok else np.array([])
log(f"阀统计：候选 {n_cand}｜回落>0.2% 剔除 {len(veto_pull)}｜抓取失败剔除 {len(veto_fail)}"
    f"｜V2 后保留 {n_cand - len(veto_pull) - len(veto_fail)}"
    f"｜回落幅度 median={np.median(pull_sorted)*100:.3f}% p10={pull_sorted[int(len(pull_sorted)*0.1)]*100:.3f}% "
    f"p90={pull_sorted[int(len(pull_sorted)*0.9)]*100:.3f}%")


def make_valve(veto):
    def _v(d, code):
        return (pd.Timestamp(d), code) not in veto
    return _v


# ---------------- 4. 源码注入：给引擎买入循环加 VALVE 过滤 ----------------
_SRC = inspect.getsource(E.run_khunter_port)
_OLD = "                for code, rsi1, close in buys[d]:"
_NEW = ("                for code, rsi1, close in (buys[d] if VALVE is None else "
        "[t for t in buys[d] if VALVE(d, t[0])]):")
assert _SRC.count(_OLD) == 1, f"引擎源码已变，注入锚点失效（count={_SRC.count(_OLD)}）"
_SRC2 = _SRC.replace(_OLD, _NEW).replace("def run_khunter_port(", "def run_khunter_port_valve(")
_NS = dict(E.__dict__)
exec(compile(_SRC2, "<valve_patched>", "exec"), _NS)
run_valve = _NS["run_khunter_port_valve"]
_NS["VALVE"] = None
log("注入完成：run_khunter_port_valve（B0=VALVE None / V2=过滤函数，同一容器）")


# ---------------- 5. 统计（照抄 optim2 summarize：nav_stats + 分年度） ----------------
def summarize(nav, tr, label, t0):
    st = E.nav_stats(nav, tr)
    if st is None:
        print(f"{label}: EMPTY", flush=True)
        return None
    tdf = pd.DataFrame(tr)
    yearly = {}
    if len(tdf):
        tdf['yr'] = pd.to_datetime(tdf['entry']).dt.year
        g = tdf.groupby('yr')['ret'].agg(['count', 'mean'])
        yearly = {int(k): {'n': int(v['count']), 'mean': round(v['mean'] * 100, 3)}
                  for k, v in g.to_dict('index').items()}
    posy = sum(1 for v in yearly.values() if v['mean'] > 0)
    print(f"{label:26s} n={st['n']:>4} wr={st['wr']:>5}% med={st['med']:>7}% mean={st['mean']:>7}% "
          f"total={st['total']:>8}% ann={st['ann']:>6}% sharpe={st['sharpe']:>6} mdd={st['maxdd']:>7}% "
          f"正年{posy}/{len(yearly)} ({time.time()-t0:.0f}s)", flush=True)
    return {**st, 'pos_years': posy, 'n_years': len(yearly), 'yearly': yearly}


# ---------------- 6. 四臂 A/B ----------------
res = {}
print("\n===== 引擎内 A/B（生产口径 PROD_KW；只差 gate 与阀）=====", flush=True)

# 6a. 自检：B0 用原版引擎跑一遍，证明补丁（VALVE=None）零行为变更
nav_o, tr_o = E.run_khunter_port(sigs, sp, **PROD_KW)
res['hybrid_wb_B0_orig'] = summarize(nav_o, tr_o, 'hybrid_wb B0 原版引擎(自检)', t0)

for gate in ('hybrid_wb', 'none'):
    for arm in ('B0', 'V2', 'V2_failpass'):
        if arm == 'V2_failpass' and n_fail == 0:
            continue
        _NS['VALVE'] = None if arm == 'B0' else make_valve(veto_pull if arm == 'V2_failpass'
                                                           else (veto_pull | veto_fail))
        kw = dict(PROD_KW)
        kw['gate'] = gate
        nav, tr = run_valve(sigs, sp, **kw)
        res[f'{gate}_{arm}'] = summarize(nav, tr, f'{gate} {arm}', t0)

# ---------------- 7. 差值与裁决 ----------------
def delta(a, b):
    if not a or not b:
        return None
    return {'d_ann_pp': round(b['ann'] - a['ann'], 2), 'd_sharpe': round(b['sharpe'] - a['sharpe'], 3),
            'd_mdd_pp': round(b['maxdd'] - a['maxdd'], 2), 'd_n': int(b['n'] - a['n'])}


deltas = {}
for gate in ('hybrid_wb', 'none'):
    deltas[f'{gate}_V2_minus_B0'] = delta(res.get(f'{gate}_B0'), res.get(f'{gate}_V2'))
_NS['VALVE'] = None

b0 = res.get('hybrid_wb_B0') or {}
print("\n===== ① 引擎基线 vs 优化 BASE（9.9%/0.684/mdd-20.91%/n=329）=====", flush=True)
print(f"  引擎 B0: ann={b0.get('ann')}% sharpe={b0.get('sharpe')} mdd={b0.get('maxdd')}% n={b0.get('n')}")
print(f"  优化 BASE: ann={OPTIM2_REF['ann']}% sharpe={OPTIM2_REF['sharpe']} mdd={OPTIM2_REF['maxdd']}% n={OPTIM2_REF['n']}")
print(f"  Δ: ann={round(b0.get('ann',0)-OPTIM2_REF['ann'],2)}pp sharpe={round(b0.get('sharpe',0)-OPTIM2_REF['sharpe'],3)} "
      f"mdd={round(b0.get('maxdd',0)-OPTIM2_REF['maxdd'],2)}pp n={b0.get('n',0)-OPTIM2_REF['n']:+d}")
same_as_orig = (b0.get('ann') == (res.get('hybrid_wb_B0_orig') or {}).get('ann')
                and b0.get('sharpe') == (res.get('hybrid_wb_B0_orig') or {}).get('sharpe'))
print(f"  自检：patched(VALVE=None) vs 原版引擎 一致 = {same_as_orig}")

print("\n===== ③ A/B 差值 =====", flush=True)
for gate in ('hybrid_wb', 'none'):
    d = deltas.get(f'{gate}_V2_minus_B0')
    if d:
        v = '提收益' if d['d_ann_pp'] > 0 else '降收益'
        r = '降回撤' if d['d_mdd_pp'] > 0 else '升回撤'
        print(f"  [{gate}] Δ年化 {d['d_ann_pp']:+.2f}pp ({v})｜Δ夏普 {d['d_sharpe']:+.3f}｜"
              f"Δ回撤 {d['d_mdd_pp']:+.2f}pp ({r})｜Δ笔数 {d['d_n']:+d}")

out = {
    "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
    "engine": "khunter_port_engine_0903.py::run_khunter_port (源码注入 run_khunter_port_valve)",
    "config": {"PROD_KW": PROD_KW, "pull_thr": PULL_THR, "max_hold": E.MAX_HOLD,
               "cost_buy_sell": [E.COST_BUY, E.COST_SELL], "backtest_start": str(E.BACKTEST_START),
               "board_only": "main", "st_skip": True,
               "state": "O2.load_idx + O2.state_ma250_volscale(idx,'none') = MA250 分域 T-1",
               "anchor_old": _OLD, "anchor_new": _NEW},
    "valve_stats": {"candidates": n_cand, "unique_stock_day_fetched": len(uniq),
                    "minute_fetch_fail": n_fail, "vetoed_by_pull": len(veto_pull),
                    "vetoed_by_fetch_fail": len(veto_fail),
                    "v2_kept": n_cand - len(veto_pull) - len(veto_fail),
                    "drop_ratio_pct": round((len(veto_pull) + len(veto_fail)) / max(n_cand, 1) * 100, 2),
                    "pull_median_pct": round(float(np.median(pull_sorted)) * 100, 3) if len(pull_sorted) else None,
                    "pull_p10_pct": round(float(pull_sorted[int(len(pull_sorted) * 0.1)]) * 100, 3) if len(pull_sorted) else None,
                    "pull_p90_pct": round(float(pull_sorted[int(len(pull_sorted) * 0.9)]) * 100, 3) if len(pull_sorted) else None,
                    "fail_list": fail_list[:80], "fail_list_truncated": n_fail > 80},
    "arms": res,
    "deltas": deltas,
    "prod_base_ref": OPTIM2_REF,
    "b0_vs_prod_base": {
        "d_ann_pp": round(b0.get('ann', 0) - OPTIM2_REF['ann'], 2),
        "d_sharpe": round(b0.get('sharpe', 0) - OPTIM2_REF['sharpe'], 3),
        "d_mdd_pp": round(b0.get('maxdd', 0) - OPTIM2_REF['maxdd'], 2),
        "d_n": b0.get('n', 0) - OPTIM2_REF['n']},
    "patch_noop_check_same_as_orig_engine": bool(same_as_orig),
    "notes": [
        "候选口径 = 引擎宽松收集 cand∧rsi1<osl_loose(=40)，覆盖两 gate 全部可能买入；阀在执行前过滤",
        "V2 主口径：分时抓取失败→不买（与上一轮 valve_kh_engine_ab_0919 的 pass_v2 定义一致）；"
        "V2_failpass 敏感性臂：失败→买",
        "gate='none' 臂仍保留 PROD_KW 其余项：卖出侧 ob_bull=75 为 gate 无关逻辑（引擎第244行），"
        "熊市买点 osl=35+low3、牛市买点 osl_bull=32 不受 gate 影响",
    ],
}
OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding='utf-8')
log(f"✅ 保存 {OUT}")
