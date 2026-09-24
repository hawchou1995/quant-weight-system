# -*- coding: utf-8 -*-
"""左侧捡漏 · 回测参考卡产物生成器（zuoce_jianlou_backtest.json）

职责边界
--------
本脚本**不做任何回测计算**，只把已冻结、已审计的留出/全期复测产物
`backtest/bt520_holdout_0924.json`（由 E 盘冻结库 bt520_turtle_regime 的
`run_r16_yearly.py::arm_s` 逐字副本在留出段/全样本上跑出）**投影**成看板
`_bt_ref_card()` 消费的字段契约（`period / total_return / max_drawdown /
sharpe / n_trades / win_rate / med_per_trade / ann_return / note`），
并保留完整门禁读数（`holdout_gate`）供审计与隔离校验器核对。

为什么单独成文件
----------------
`backtest/zuoce_jianlou_daily.py` 只做**入场侧单日判定**，不重做组合回测
（见该文件 docstring 的「职责边界」），因此不产出本卡片。本脚本即为该产物的
唯一权威来源；幂等，可反复运行。

诚实原则（零生产变更纪律）
--------------------------
1. 所有数字均来自 `bt520_holdout_0924.json`，一个都不手输、一个都不外推。
2. 若该来源文件缺失或字段缺失 → **不写盘**，rc=3（宁可卡片显示「未到盘」，
   也绝不编数字）。
3. 留出段复测门 `verdict.total == "不通过"` ⇒ `trading_enabled=false`、
   `gate` 如实标注；本产物**不得**被解读为可交易。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from datetime import datetime, timezone, timedelta

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent

SRC = HERE / "bt520_holdout_0924.json"          # 唯一数据来源（冻结审计产物）
OUT = HERE / "zuoce_jianlou_backtest.json"      # 本脚本产出
PAPER_STATE = HERE / "zuoce_jianlou_paper_state.json"

STRATEGY = "左侧捡漏"
STRATEGY_KEY = "zuoce_jianlou"
RULE_VERSION = "zuoce-jianlou.leftbook.bt520.v1"

# 契约要部署的支 = 纯 Book B（wB=1.0）；预注册冻结对象 = wB=0.8（两者都在读数里）
DEPLOY_OBJECT = "wB=1.0,KB=5"
PREREG_OBJECT = "wB=0.8,KB=5"

CST = timezone(timedelta(hours=8))


def sha256_of(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def pick(d: dict, *keys, default=None):
    """按 keys 路径取值；任一层缺失即返回 default（缺失就写 null，不外推）。"""
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


# 契约要部署的支 = 纯 Book B（wB=1.0）；预注册冻结对象 = wB=0.8（两者都在读数里）
# 注意：同一对象在两个段里的键名口径不同（实测）——
#   stage_p.parity_full_sample 的键 = "中放·full·wB=1.0·KB=5"
#   A1/A2/A3.by_object 的键       = "wB=1.0,KB=5"
DEPLOY_OBJECT = "wB=1.0,KB=5"
PREREG_OBJECT = "wB=0.8,KB=5"
DEPLOY_PFS_KEY = "中放·full·wB=1.0·KB=5"
PREREG_PFS_KEY = "中放·full·wB=0.8·KB=5"


def num(v):
    """只接受真数字（int/float，bool 除外）；None/缺失 → None 让字段消失。"""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return round(float(v), 2)


def build() -> dict:
    if not SRC.exists():
        raise FileNotFoundError("缺少唯一数据来源 %s（拒绝凭空生成）" % SRC.name)
    src = json.loads(SRC.read_text(encoding="utf-8"))

    pfs = pick(src, "stage_p", "parity_full_sample", default={}) or {}
    fs = pfs.get(DEPLOY_OBJECT) or {}
    fs = pfs.get(DEPLOY_PFS_KEY) or {}
    fs_prereg = pfs.get(PREREG_PFS_KEY) or {}
    if not fs:
        raise KeyError("来源缺少 stage_p.parity_full_sample[%s]" % DEPLOY_PFS_KEY)
    verdict = pick(src, "verdict", default={}) or {}
    a1 = pick(src, "A1", default={}) or {}
    a2 = pick(src, "A2", default={}) or {}
    a3 = pick(src, "A3", default={}) or {}
    a4 = pick(src, "A4", default={}) or {}
    a5 = pick(src, "A5", default={}) or {}

    a1_by = (a1.get("by_object") or {})
    a2_by = (a2.get("by_object") or {})
    a3_by = (a3.get("by_object") or {})
    a1_v = num(pick(a1_by, DEPLOY_OBJECT, "value"))
    a2_v = num(pick(a2_by, DEPLOY_OBJECT, "value"))
    a3_v = num(pick(a3_by, DEPLOY_OBJECT, "value"))
    a1_pre = num(pick(a1_by, PREREG_OBJECT, "value"))
    a2_pre = num(pick(a2_by, PREREG_OBJECT, "value"))

    holdout = pick(src, "prereg", "holdout", default={}) or {}
    panel_span = pick(src, "execution_notes", "panel", "span", default=None)
    parity = pick(src, "execution_notes", "parity_checks",
                  "vs_e_drive_out_r16_yearly", default=None)

    gate_pass = (verdict.get("total") == "通过")
    gate_txt = (
        "留出段复测门【未通过】：A1 中位年化 %s%%、A2 单路径年化 %s%%（均为负，禁标可交易）；"
        "A3 回撤 %s%% 通过；A4 全样本口径 %s%% 通过 / 留出段口径 %s%% 未通过；A5 成本×3 %s%% 通过。"
        "判定规则 = A1–A5 全满足才通过 → 总判定「%s」。"
        % (
            _s(a1_v), _s(a2_v), _s(a3_v),
            _s(num(a4.get("value"))), _s(num(pick(a4, "holdout_reading", "value"))),
            _s(num(a5.get("value"))), verdict.get("total"),
        )
    )

    out = {
        "schema": "zuoce_jianlou_backtest/v1",
        "strategy": STRATEGY,
        "strategy_key": STRATEGY_KEY,
        "rule_version": RULE_VERSION,
        "generated_at": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
        "generated_by": "backtest/build_zuoce_backtest_ref.py"
                        "（投影 %s，不含任何重算）" % SRC.name,

        # ---- _bt_ref_card 消费的字段契约（缺字段就不渲染，绝不编） ----
        "period": "面板区间 %s（全期 40-draw 主口径）｜留出门 %s → %s" % (
            panel_span or "—",
            holdout.get("start") or "2016-01-04",
            holdout.get("end") or "2017-12-29",
        ),
        "total_return": None,          # 来源无全期总收益读数 → 如实留空
        "max_drawdown": num(fs.get("mdd_median")),
        "sharpe": None,                # 来源不含夏普 → 如实留空
        "n_trades": num(fs.get("n_trades_median")),
        "win_rate": num(fs.get("single_path_wr")),
        "med_per_trade": num(fs.get("single_path_med_pct")),
        "ann_return": num(fs.get("median_annual")),
        "note": ("⚠ 留出门未过（A1/A2 为负）→ 只上回测数据、不开模拟盘、不写净值。"
                 "上列区间/回撤/交易数/胜率/单笔中位/年化均为**全期**（非留出段）读数，"
                 "仅作策略形态参考，**不代表可交易**；" + gate_txt),

        # ---- 完整门禁读数（审计/隔离校验器用，超出卡片契约的部分卡片会忽略） ----
        "trading_enabled": False,
        "gate": "holdout_gate_failed",
        "gate_note": gate_txt,
        "kpi_scope": "full-sample (非留出段)",
        "deploy_object": DEPLOY_OBJECT,
        "prereg_object": PREREG_OBJECT,
        "full_sample": {
            "caliber": "全样本 40-draw 年化中位数（seed=20260926+d, d=0..39, 244 日/年）",
            "object": DEPLOY_OBJECT,
            "median_annual": num(fs.get("median_annual")),
            "mean_annual": num(fs.get("mean_annual")),
            "worst_draw": num(fs.get("worst_draw")),
            "best_draw": num(fs.get("best_draw")),
            "pos_ratio": num(fs.get("pos_ratio")),
            "mdd_median": num(fs.get("mdd_median")),
            "mdd_worst": num(fs.get("mdd_worst")),
            "n_trades_median": num(fs.get("n_trades_median")),
            "single_path_annual": num(fs.get("single_path_annual")),
            "single_path_wr": num(fs.get("single_path_wr")),
            "single_path_med_pct": num(fs.get("single_path_med_pct")),
            "prereg_object_median_annual": num(fs_prereg.get("median_annual")),
        },
        "holdout_gate": {
            "caliber": "留出段 %s → %s（%s 交易日声明，实测可交易 %s 日）· 40 draws"
                       % (holdout.get("start"), holdout.get("end"),
                          holdout.get("n_days"),
                          pick(src, "stage_p", "diagnostics", "tradable_holdout_days")),
            "rule": verdict.get("rule"),
            "total": verdict.get("total"),
            "reason": verdict.get("reason"),
            "unaffected_by_readings": verdict.get("unaffected_by_readings"),
            "A1_median_annual": {
                "deploy_object": a1_v, "prereg_object": a1_pre,
                "threshold": num(a1.get("threshold")), "pass": a1.get("pass"),
            },
            "A2_single_path_annual": {
                "deploy_object": a2_v, "prereg_object": a2_pre,
                "threshold": num(a2.get("threshold")), "pass": a2.get("pass"),
            },
            "A3_mdd": {
                "deploy_object": a3_v,
                "threshold": num(a3.get("threshold")), "pass": a3.get("pass"),
            },
            "A4_neighborhood": {
                "full_sample_reading": {"value": num(a4.get("value")),
                                        "threshold": num(a4.get("threshold")),
                                        "pass": a4.get("pass"),
                                        "caliber": a4.get("caliber_reading")},
                "holdout_reading": {"value": num(pick(a4, "holdout_reading", "value")),
                                    "pass": pick(a4, "holdout_reading", "pass")},
                "note": a4.get("note"),
            },
            "A5_cost_x3": {"value": num(a5.get("value")),
                           "threshold": num(a5.get("threshold")),
                           "pass": a5.get("pass"),
                           "caliber": a5.get("caliber")},
            "warmup_degeneracy": pick(src, "execution_notes", "warmup_degeneracy", default=None),
            "known_limitations": pick(src, "execution_notes", "known_limitations", default=None),
        },
        "source": {
            "artifact": SRC.name,
            "artifact_sha256": sha256_of(SRC),
            "artifact_bytes": SRC.stat().st_size,
            "prereg_file": pick(src, "prereg", "file"),
            "prereg_sha256": pick(src, "prereg", "sha256"),
            "engine_sha256": pick(src, "prereg", "engine", "sha256"),
            "arm_impl_sha256": pick(src, "prereg", "arm_impl", "sha256"),
            "panel_span": panel_span,
            "parity_vs_frozen_repo": parity,
            "frozen_repo_readonly": pick(src, "execution_notes", "frozen_readonly_check",
                                         "note"),
        },
        "gate_pass": gate_pass,
    }
    return out


def _s(v):
    return "—" if v is None else ("%+.2f" % v)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="左侧捡漏回测参考卡产物生成器（只投影、不重算）")
    ap.add_argument("--dry-run", action="store_true", help="只打印摘要，不写盘")
    ap.add_argument("--out-json", default=None, help="覆盖输出路径（默认 backtest/zuoce_jianlou_backtest.json）")
    args = ap.parse_args(argv)

    try:
        d = build()
    except (FileNotFoundError, KeyError) as e:
        print("[FAIL] %s" % e, file=sys.stderr)
        return 3

    # 与 paper_state 的一致性自检（若在盘）：门的字段必须一致
    if PAPER_STATE.exists():
        try:
            ps = json.loads(PAPER_STATE.read_text(encoding="utf-8"))
            if ps.get("trading_enabled") is True:
                print("[FAIL] paper_state.trading_enabled=True 与未过门矛盾", file=sys.stderr)
                return 3
            d["paper_state_as_of"] = ps.get("as_of")
            d["paper_state_gate"] = ps.get("gate")
        except Exception as e:  # noqa: BLE001
            print("[WARN] paper_state 读取失败（不阻断）：%s" % e, file=sys.stderr)

    dest = pathlib.Path(args.out_json) if args.out_json else OUT
    txt = json.dumps(d, ensure_ascii=False, indent=2)
    if args.dry_run:
        print("[dry-run] %s → %d 字符" % (dest.name, len(txt)))
        print("  period          = %s" % d["period"])
        print("  ann_return      = %s (全期 40-draw 中位年化 %%)" % d["ann_return"])
        print("  max_drawdown    = %s" % d["max_drawdown"])
        print("  n_trades        = %s" % d["n_trades"])
        print("  win_rate        = %s" % d["win_rate"])
        print("  med_per_trade   = %s" % d["med_per_trade"])
        print("  gate_pass       = %s" % d["gate_pass"])
        print("  verdict.total   = %s" % d["holdout_gate"]["total"])
        return 0

    dest.write_text(txt + "\n", encoding="utf-8")
    print("[OK] 写盘 %s（%d 字节）" % (dest, dest.stat().st_size))
    print("     留出门判定 = %s / A1 %s / A2 %s / A3 %s / A4(全期) %s / A5 %s"
          % (d["holdout_gate"]["total"], d["holdout_gate"]["A1_median_annual"]["pass"],
             d["holdout_gate"]["A2_single_path_annual"]["pass"],
             d["holdout_gate"]["A3_mdd"]["pass"],
             d["holdout_gate"]["A4_neighborhood"]["full_sample_reading"]["pass"],
             d["holdout_gate"]["A5_cost_x3"]["pass"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
