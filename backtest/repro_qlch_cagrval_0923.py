# -*- coding: utf-8 -*-
"""复算 qlch T+1 复测卡片的年化口径（R-qlch-cagrval-0923）。

背景：`backtest/qlch_bt_t1exit_0922.json` 的 `cagr_val`（验证窗年化）原用**绝对净值水平**年化
（v[-1]**(1/yrs)-1），在 2022+ 段被放大；训练窗因起点净值=1.0 而看不出该缺陷。
本脚本仅依赖 `_tmp_0922_t1exit_v2.json` 的逐年收益（yr，单位 %），无需引擎/面板，可独立复算。

用法: python backtest/repro_qlch_cagrval_0923.py
退出码: 0 = 复算与原卡（绝对净值口径）在 0.5pp 内一致且修正表已写入 JSON；1 = 不一致
"""
import io, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "_tmp_0922_t1exit_v2.json")
CARD = os.path.join(HERE, "qlch_bt_t1exit_0922.json")
YR_VAL = 4.6863   # 2022-01-04 → 2026-09-22

def cum(yr, keys):
    v = 1.0
    for k in keys:
        v *= (1.0 + yr.get(k, 0.0) / 100.0)
    return v

def main():
    src = json.load(io.open(SRC, encoding="utf-8"))
    card = json.load(io.open(CARD, encoding="utf-8"))
    rows, bad = [], []
    for a in card["arms"]:
        arm = a["name"].split()[0]
        tr, va = src.get("TR20|" + arm), src.get("VA20|" + arm)
        if not (tr and va):
            continue
        ks_tr, ks_va = sorted(tr["yr"]), sorted(va["yr"])
        traded = [k for k in ks_tr if abs(tr["yr"][k]) > 1e-9]
        c_tr, c_va = cum(tr["yr"], ks_tr), cum(va["yr"], ks_va)
        cagr_4y = (c_tr ** (1.0 / len(traded)) - 1) * 100
        abs_recalc = ((c_tr * c_va) ** (1.0 / YR_VAL) - 1) * 100
        fix = (c_va ** (1.0 / YR_VAL) - 1) * 100
        raw = a.get("cagr_val")
        rows.append((arm, tr["cagr"], cagr_4y, raw, abs_recalc, fix, (c_va - 1) * 100))
        if raw is not None and abs(raw - abs_recalc) > 0.5:
            bad.append((arm, raw, abs_recalc))
        for key, val in (("cagr_4y", cagr_4y), ("cagr_val_abs_recalc", abs_recalc), ("cagr_val_fix", fix)):
            if abs(float(a.get(key, -999)) - val) > 0.01:
                bad.append((arm + "." + key, a.get(key), round(val, 2)))
    print("臂   训练6年%  训练4年%  卡验证窗%  绝对净值复算%  修正后%   验证累计%")
    for arm, c6, c4, raw, ab, fx, vc in rows:
        print("%-4s %8.2f %9.2f %10s %14.2f %9.2f %10.2f"
              % (arm, c6, c4, raw, ab, fx, vc))
    print()
    if bad:
        print("不一致:", bad)
        return 1
    print("复算一致（绝对净值口径复现原卡 ≤0.5pp；修正字段与 JSON 一致）；修正后 E4 验证窗年化 = %.2f%%" % rows[-1][5])
    return 0

if __name__ == "__main__":
    sys.exit(main())
