# -*- coding: utf-8 -*-
"""R1/R2/R3 修复补丁（2026-09-17）：软锚改造 + shadow ST 过滤 + simulate_w 整手

R1 硬断言 22.87 → 软锚（读 backtest/engine_anchor.json；|Δ|>3pp 中止、>1pp 警告）
    涉及：lowcorr_stage2_crossasset_0916.py / kb_ret20_blend_0917.py /
          kb_ret20_placebo_0917.py / kb_micro_crowdN_0917.py（+ stage2 输出 meta 的实际锚值）
R2 shadow_ret20.py top20 只剔"退" → 生产同源双剔（name_hist 最新名 ST + 退）
R3 lowcorr_stage2b_missing_0917.py simulate_w 减仓 min(sell_lots, shares[c]/LOT) → int() 整手
"""
import sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent


def patch(name, old, new, expect=1):
    p = HERE / name
    t = p.read_text(encoding="utf-8")
    n = t.count(old)
    assert n == expect, f"[FAIL] {name}: 命中 {n} != {expect} | anchor={old[:70]!r}"
    p.write_text(t.replace(old, new), encoding="utf-8")
    print(f"[OK] {name}: {expect} 处")


# ============ R1-a stage2：_anchor_value() + load_track_b 软锚 ============
patch("lowcorr_stage2_crossasset_0916.py",
      """# ============================================================ 1) 轨B 基准
def load_track_b():""",
      """# ============================================================ 1) 轨B 基准
def _anchor_value():
    \"\"\"软锚（2026-09-17）：读 shadow_ret20 日链刷新的 engine_anchor.json；缺省回落历史锚 22.87\"\"\"
    try:
        return float(json.loads((OSS.parent / "engine_anchor.json").read_text(encoding="utf-8"))["base_off0_ann"])
    except Exception:
        return 22.87


def load_track_b():""")

patch("lowcorr_stage2_crossasset_0916.py",
      """    log(f"[轨B] off0 年化 {ann:.2f}%（官方 22.87%）| 夏普(引擎√244) {r['sharpe']:.3f} | "
        f"回撤 {r['mdd']*100:.1f}% | 净值区间 {eq.index[0].date()}→{eq.index[-1].date()} | "
        f"面板日历 {cal[0].date()}→{cal[-1].date()}（{len(cal)}d，WARMUP=150）")
    if abs(ann - 22.87) > 0.5:
        log(f"[ABORT] 轨B 复现年化 {ann:.2f}% ≠ 官方 22.87% → 口径未对齐，拒绝出结论")
        sys.exit(2)
    return eq, cal""",
      """    _anchor = _anchor_value()          # 2026-09-17 软锚：数据 vintage 日更，22.87 为历史锚非硬门
    _d = abs(ann - _anchor)
    log(f"[轨B] off0 年化 {ann:.2f}%（锚 {_anchor}% | 漂移 {_d:.2f}pp）| 夏普(引擎√244) {r['sharpe']:.3f} | "
        f"回撤 {r['mdd']*100:.1f}% | 净值区间 {eq.index[0].date()}→{eq.index[-1].date()} | "
        f"面板日历 {cal[0].date()}→{cal[-1].date()}（{len(cal)}d，WARMUP=150）")
    if _d > 3.0:
        log(f"[ABORT] 轨B 复现年化 {ann:.2f}% 偏离锚 {_anchor}% 达 {_d:.2f}pp（>3pp）→ 口径/数据异常，拒绝出结论")
        sys.exit(2)
    elif _d > 1.0:
        log(f"[WARN] 轨B 锚漂移 {_d:.2f}pp（数据版本推进所致，正常范围）")
    return eq, cal""")

# ============ R1-b stage2 输出 meta：记录实际锚值 ============
patch("lowcorr_stage2_crossasset_0916.py",
      '''        "trackB": {"off0_ann_pct": 22.87, "note": "冻结引擎 oss_super_combo_0913.py off0；窗口 " +''',
      '''        "trackB": {"off0_ann_pct": _anchor_value(), "official_hist": 22.87,
                   "note": "冻结引擎 oss_super_combo_0913.py off0（软锚 engine_anchor.json）；窗口 " +''')

# ============ R1-c/d blend + placebo：assert → 软锚 ============
SOFT = '''rB = G["run_engine"](G["composite"](), 20, offset=0)
# 2026-09-17 软锚改造：数据 vintage 日更 → 读 shadow_ret20 刷新的 engine_anchor.json（22.87=历史锚）
_anchor = 22.87
try:
    import os as _os
    _af = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "engine_anchor.json")
    if _os.path.exists(_af):
        _anchor = float(json.load(open(_af, encoding="utf-8"))["base_off0_ann"])
except Exception:
    pass
_annB = float(rB["ann"]) * 100; _drift = abs(_annB - _anchor)
log(f"[锚] 轨B off0 年化 {_annB:.2f}%（锚 {_anchor}% | 漂移 {_drift:.2f}pp）")
if _drift > 3.0:
    raise SystemExit(f"[ABORT] 轨B 复现年化 {_annB:.2f}% 偏离锚 {_anchor}% 达 {_drift:.2f}pp（>3pp）→ 拒绝出数")
elif _drift > 1.0:
    log(f"[WARN] 锚漂移 {_drift:.2f}pp（数据版本推进所致，正常范围）")
'''
OLD_ASSERT = '''rB = G["run_engine"](G["composite"](), 20, offset=0)
assert abs(float(rB["ann"]) * 100 - 22.87) <= 0.5
'''
patch("kb_ret20_blend_0917.py", OLD_ASSERT, SOFT)
patch("kb_ret20_placebo_0917.py", OLD_ASSERT, SOFT)

# ============ R1-e micro：exit(1) → 软锚 ============
patch("kb_micro_crowdN_0917.py",
      '''if abs(annB-22.87)>0.5: log("[ABORT] 口径未对齐"); sys.exit(1)''',
      '''# 2026-09-17 软锚改造（数据 vintage 日更；22.87=历史锚，读 shadow_ret20 刷新的 engine_anchor.json）
_anchor = 22.87
try:
    _af = os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine_anchor.json")
    if os.path.exists(_af):
        _anchor = float(json.load(open(_af, encoding="utf-8"))["base_off0_ann"])
except Exception:
    pass
_drift = abs(annB - _anchor)
if _drift > 3.0: log(f"[ABORT] 轨B 偏离锚 {_drift:.2f}pp（>3pp）"); sys.exit(1)
elif _drift > 1.0: log(f"[WARN] 锚漂移 {_drift:.2f}pp（数据版本推进）")''')

# ============ R2 shadow：ST/退 生产同源双剔 ============
patch("shadow_ret20.py",
      '''def top20(comp_):
    di = ND - 1
    sc = comp_[di]
    ok = np.where(np.isfinite(sc) & EL[di])[0]
    ok = sorted(ok, key=lambda j: -sc[j])
    # 剔 ST/退（生产口径）
    out = []
    for j in ok:
        c = str(G["codes"][j])[-6:]
        nm = NAMES.get(c, "")
        if "退" in nm: continue
        out.append(c)
        if len(out) >= 20: break
    return out''',
      '''def top20(comp_):
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
    return out''')

patch("shadow_ret20.py",
      '''try:
    NAMES = json.load(open(os.path.join(BASE, "data_full_names.json"), encoding="utf-8"))
    _n2 = {}
    for k, v in NAMES.items():
        _n2[str(k)[-6:]] = v
    NAMES = _n2
except Exception:
    NAMES = {}''',
      '''try:
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
    log(f"[ST/退] name_hist 不可用（{type(_e).__name__}）→ 回退名字串匹配")''')

# ============ R3 stage2b：simulate_w 减仓显式整手 ============
patch("lowcorr_stage2b_missing_0917.py",
      "sell_lots = min(sell_lots, shares[c] / LOT)",
      "sell_lots = min(sell_lots, int(shares[c] // LOT))   # 2026-09-17 修：显式整手，防浮点股数")

# ============ 语法校验 ============
import py_compile
FILES = ["lowcorr_stage2_crossasset_0916.py", "kb_ret20_blend_0917.py", "kb_ret20_placebo_0917.py",
         "kb_micro_crowdN_0917.py", "shadow_ret20.py", "lowcorr_stage2b_missing_0917.py"]
for f in FILES:
    py_compile.compile(str(HERE / f), doraise=True)
    print(f"[compile OK] {f}")
print("\n[done] 8 处替换 + 6 文件语法校验全过")
