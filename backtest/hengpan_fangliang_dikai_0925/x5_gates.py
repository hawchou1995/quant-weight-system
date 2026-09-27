# -*- coding: utf-8 -*-
"""x5_gates.py — 准入门槛扫描：量比下限/上限 × 盈亏比下限（2026-09-27，R-hpdk-gates-0927）

用户问题：「如果调整准入门槛，比如量比要多于多少、盈亏比要大于多少，回测数据会有改善吗？」

口径纪律：不重写任何逻辑 —— 复用 x2_sens 的 run_variant / sim_portfolio / 面板缓存，
只切换 oos_run.py 的运行期开关 P[VOLBR_MIN] / P[VOLBR_MAX] / P[RR_MIN]（默认值 = 无操作）。

定义：
  量比 VOLBR = volume[T] / mean(volume[T−20..T−1])   （窗口不含当日，与预注册 §1.3 一致）
  盈亏比 RR   = P["TP"] / ATR20%                       （止盈距离 ÷ 20 日平均真实波幅占收盘比）
  止盈 +2% ⇒ RR = 2% / ATR20% ；ATR20 越大 ⇒ RR 越小（波动越大越难在 2 日内到达 +2%）

基线等价性：base 臂读数必须与 v1.4（未加门槛时）逐位相同，否则视为口径漂移，脚本非零退出。

用法: python x5_gates.py [--cache DIR]
"""
import sys, json, argparse, pathlib
import numpy as np

OUT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(OUT))
import x2_sens as X                                     # noqa: E402

V4_BASE_ALL = dict(ann=47.77, mdd=-29.13, sharpe=2.12, n_trades=23759, mean_per_trade=0.4028, win_rate=60.63)
V4_BASE_2018 = dict(ann=64.24, mdd=-29.13, sharpe=2.44, n_trades=21146, mean_per_trade=0.4264, win_rate=60.71)

ARMS = [("base 基线(无门槛)", {})]
for v in (0.5, 0.8, 1.0, 1.2, 1.5):
    ARMS.append(("量比≥%.1f" % v, {"VOLBR_MIN": v}))
for v in (1.0, 1.5, 2.0, 3.0):
    ARMS.append(("量比≤%.1f" % v, {"VOLBR_MAX": v}))
for v in (1.0, 1.5, 2.0, 3.0, 4.0):
    ARMS.append(("盈亏比≥%.1f" % v, {"RR_MIN": v}))
ARMS += [("量比≤1.5 & 盈亏比≥2.0", {"VOLBR_MAX": 1.5, "RR_MIN": 2.0}),
         ("量比≤2.0 & 盈亏比≥1.5", {"VOLBR_MAX": 2.0, "RR_MIN": 1.5}),
         ("量比0.5~1.5 & 盈亏比≥2.0", {"VOLBR_MIN": 0.5, "VOLBR_MAX": 1.5, "RR_MIN": 2.0})]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=str(pathlib.Path(str(X.OUT)).parents[1] / ".x3cache"))
    ap.add_argument("--reuse", action="store_true", help="复用已落盘的 _v_gNN_trades.jsonl，跳过重放")
    a = ap.parse_args()
    cache = pathlib.Path(a.cache); cache.mkdir(parents=True, exist_ok=True)
    mod = X.load_mod()
    sha = mod.FROZEN_SHA
    print("冻结脚本 SHA256 = %s" % sha, flush=True)
    cal, syms, F, done = X.get_panel(mod, cache, True)

    res = {}
    for i, (label, ov) in enumerate(ARMS):
        tag = "g%02d" % i
        print("[%2d/%d] %s  %s" % (i + 1, len(ARMS), label, ov if ov else ""), flush=True)
        _tf = cache / ("_v_%s_trades.jsonl" % tag)
        if a.reuse and _tf.exists():
            recs = [json.loads(x) for x in _tf.read_text(encoding="utf-8").splitlines() if x.strip()]
            P = dict(X.BASE_P)
            print("      [reuse] %d 笔" % len(recs), flush=True)
        else:
            recs, P = X.run_variant(mod, cache, cal, F, done, tag, ov or None, None)
        assert mod.FROZEN_SHA == sha, "冻结脚本 SHA 被改动！"
        m = X.sim_portfolio(recs, cal, syms, F, 10, 20, X.BASE_P["COST_SIDE"]) if recs else None
        m18 = (X.sim_portfolio(recs, cal, syms, F, 10, 20, X.BASE_P["COST_SIDE"], start="2018-01-01")
               if recs else None)
        res[label] = dict(overrides=ov, n_trades=len(recs),
                          n_days=len({r["signal_date"] for r in recs}),
                          per_day=round(len(recs) / max(1, len({r["signal_date"] for r in recs})), 2),
                          all=m, w2018=m18)
        if m:
            print("      全窗 年化 %+8.2f%% MDD %7.2f%% 夏普 %5s 胜率 %5.2f%% 净均 %+7.4f%% 净中 %+7.4f%% 笔数 %6d 日均 %.2f"
                  % (m["ann"], m["mdd"], m["sharpe"], m["win_rate"], m["mean_per_trade"],
                     m["med_per_trade"], m["n_trades"], res[label]["per_day"]), flush=True)
            if m18:
                print("      2018+ 年化 %+8.2f%% MDD %7.2f%% 夏普 %5s 胜率 %5.2f%% 笔数 %6d"
                      % (m18["ann"], m18["mdd"], m18["sharpe"], m18["win_rate"], m18["n_trades"]),
                      flush=True)

    b = res["base 基线(无门槛)"]["all"]
    ok = all(abs(b[k] - V4_BASE_ALL[k]) < 0.005 for k in V4_BASE_ALL)
    print("\n[基线等价性] base 全窗 vs v1.4 期望 %s" % V4_BASE_ALL)
    print("            实际 %s  => %s" % ({k: b[k] for k in V4_BASE_ALL}, "一致 ✅" if ok else "不一致 ❌"))

    payload = dict(frozen_script_sha256=sha, arms=res,
                   defs={"VOLBR": "volume[T] / mean(volume[T-20..T-1])（不含当日）",
                         "RR": "P[TP] / ATR20%；ATR20% = mean(TR)/close，TR=max(H-L,|H-Cp|,|L-Cp|)",
                         "TP": 0.02},
                   baseline_equiv_v14=V4_BASE_ALL, baseline_equiv_ok=bool(ok),
                   note="所有门槛都会改变当日候选池 ⇒ 横截面 z 重算 ⇒ 选股整体改变（与板块限定同一机制）")
    (OUT / "evidence_gates_scan.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                                                 encoding="utf-8")
    print("[out] evidence_gates_scan.json", flush=True)
    print("x5_gates.py DONE")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
