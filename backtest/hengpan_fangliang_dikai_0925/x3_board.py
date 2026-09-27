# -*- coding: utf-8 -*-
"""x3_board.py — 「只买主板」vs「全池」同尺子对比（2026-09-27，R-hpdk-board-0927）

不重写任何逻辑：复用 x2_sens 的 run_variant / sim_portfolio / get_panel（其面板缓存复用），
只切换 oos_run.py 的运行期开关 P["MAINBOARD"]。
两个臂跑**同一份面板、同一套组合记账规则**，仅资格掩码不同 ⇒ 差异全部来自板块限定。

用法: python x3_board.py [--cache DIR]
"""
import sys, json, argparse, pathlib, time
import numpy as np

OUT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(OUT))
import x2_sens as X                                    # noqa: E402

R = X.R
ARMS = [("全池(现状)", False), ("主板(新)", True)]
KSLOTS = [20, 4, 6]


def board_of(s):
    if s[:2] == "sh" and s[2:5] in ("600", "601", "603", "605"):
        return "主板"
    if s[:2] == "sz" and s[2:5] in ("000", "001", "002", "003"):
        return "主板"
    if s[:2] == "sz" and s[2:5] in ("300", "301", "302"):
        return "创业板"
    if s[:2] == "sh" and s[2:5] == "688":
        return "科创板"
    return "其他"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=str(X.OUT.parent.parent / ".x3cache"))
    a = ap.parse_args()
    cache = pathlib.Path(a.cache); cache.mkdir(parents=True, exist_ok=True)
    mod = X.load_mod()
    sha = mod.FROZEN_SHA
    print("冻结脚本 SHA256 = %s" % sha, flush=True)
    cal, syms, F, done = X.get_panel(mod, cache, True)
    T, N = F["C"].shape
    from collections import Counter
    comp = Counter(board_of(s) for s in syms)
    print("面板 %d 列 / %d 只：%s" % (T, N, dict(comp)), flush=True)

    res, recs_by = {}, {}
    for label, mb in ARMS:
        tag = "mb_on" if mb else "mb_off"
        print("[arm] %s (MAINBOARD=%s)" % (label, mb), flush=True)
        recs, P = X.run_variant(mod, cache, cal, F, done, tag, {"MAINBOARD": mb}, None)
        recs_by[label] = recs
        assert mod.FROZEN_SHA == sha, "冻结脚本 SHA 被改动！"
        days = len({r["signal_date"] for r in recs})
        picks = {s for r in recs for s in [r["sym"]]}
        res[label] = {"n_trades": len(recs), "n_signal_days": days,
                      "n_unique_syms": len(picks),
                      "syms_board": dict(Counter(board_of(s) for s in picks)),
                      "by_kslot": {}}
        for ks in KSLOTS:
            m = X.sim_portfolio(recs, cal, syms, F, 10, ks, X.BASE_P["COST_SIDE"])
            res[label]["by_kslot"][str(ks)] = m
            if m:
                print("    KSLOT=%2d  年化 %+8.2f%% | MDD %7.2f%% | 夏普 %5s | 胜率 %5.2f%% | "
                      "净均 %+7.4f%% | 净中 %+7.4f%% | 笔数 %6d | 占用 %6.2f%% | 负年 %d/%d"
                      % (ks, m["ann"], m["mdd"], m["sharpe"], m["win_rate"], m["mean_per_trade"],
                         m["med_per_trade"], m["n_trades"], m["deploy_pct"], m["neg_years"], m["n_years"]),
                      flush=True)
        # 2018+ 窗口
        res[label]["by_kslot_2018"] = {}
        for ks in (20, 4):
            res[label]["by_kslot_2018"][str(ks)] = X.sim_portfolio(
                recs, cal, syms, F, 10, ks, X.BASE_P["COST_SIDE"], start="2018-01-01")

    payload = dict(frozen_script_sha256=sha, panel=dict(T=int(T), N=int(N), boards=dict(comp)),
                   kslots=KSLOTS, arms=res,
                   note=("同一面板、同一组合记账规则；仅 P[MAINBOARD] 不同。"
                         "主板 = sh600/601/603/605 + sz000/001/002/003。"))
    (OUT / "evidence_board.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                                            encoding="utf-8")
    print("\n[out] evidence_board.json", flush=True)

    # 分年度对照（KSLOT=20，全窗）
    print("\n分年度（KSLOT=20，全窗）:")
    yrs = sorted({y for lab in res for y in (res[lab]["by_kslot"]["20"] or {}).get("yearly", {})})
    print("  年份     全池      主板")
    for y in yrs:
        a = res["全池(现状)"]["by_kslot"]["20"]["yearly"].get(y)
        b = res["主板(新)"]["by_kslot"]["20"]["yearly"].get(y)
        print("  %s  %+8.2f  %+8.2f" % (y, (a if a is not None else float("nan")),
                                        (b if b is not None else float("nan"))))
    print("x3_board.py DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
