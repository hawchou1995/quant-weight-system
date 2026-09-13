# -*- coding: utf-8 -*-
"""补丁 7：实盘 ST/退市过滤落地
- 轨A（冷门低波）：仅排除名称含"退"（退市整理期）；保留 ST（回测：全排 ST 减收益 7.3pp；仅排"退"零成本）
- 轨B（A4D）：排除 ST/*ST/退（回测：+3.2pp/回撤 -2.5pp/相位一致改善）
- 轨C：基金无此问题
"""
import io

ROOT = r"D:\Documents\Workbuddy\股票基金\quant-weight-system"

# ================= A. signal_satellite_0913.py =================
P1 = ROOT + r"\backtest\signal_satellite_0913.py"
t1 = io.open(P1, encoding="utf-8").read()

# A1. 过滤集合加载（插在 LAST_DAY 定义后）
anchor1 = 'LAST_DAY = max(days_all)'
assert anchor1 in t1
loader = anchor1 + '''

# 风险名称过滤（2026-09-13 落地）：轨A 仅排"退"；轨B 排 ST/*ST/退（回测依据见 st_filter_0913.json）
_nh = pd.read_csv(BASE / "data_fundamental" / "name_hist.csv", dtype={"code": str})
_nh = _nh.sort_values("TRADE_DATE").groupby("code").tail(1)
_name = _nh.set_index("code")["SECURITY_NAME_ABBR"].astype(str)
TUI_SET = set(_name[_name.str.contains("退")].index)
ST_SET = set(_name[_name.str.contains("ST")].index)'''
t1 = t1.replace(anchor1, loader, 1)

# A2. signal_ln_atr 过滤：跳过"退"
old_a = "        if len(d) < 180 or d.index[-1] != LAST_DAY:\n            continue   # ⚠ 2026-09-13 修复：必须当日有行情（剔除退市死票，与回测口径一致）"
assert old_a in t1
t1 = t1.replace(old_a, old_a + "\n        if code in TUI_SET:\n            continue   # 退市整理期排除（回测零成本）", 1)

# A3. signal_a4d_orig：ST/退 过滤并把清单补足 20
old_b = """        di = gg["ND"] - 1
        sc = gg["COMP_A4"][di]
        ok = np.where(np.isfinite(sc) & gg["ELIG_A4"][di])[0]
        ok = sorted(ok, key=lambda j: -sc[j])[:20]"""
assert old_b in t1, "a4d block missing"
new_b = """        di = gg["ND"] - 1
        sc = gg["COMP_A4"][di]
        ok = np.where(np.isfinite(sc) & gg["ELIG_A4"][di])[0]
        ok = sorted(ok, key=lambda j: -sc[j])
        ok = [j for j in ok if gg["codes"][j] not in ST_SET and gg["codes"][j] not in TUI_SET][:20]   # ST/退过滤（回测 +3.2pp/回撤-2.5pp）"""
t1 = t1.replace(old_b, new_b, 1)
io.open(P1, "w", encoding="utf-8").write(t1)
print("signal_satellite: 过滤落地")

# ================= B. build_satellite_pool.py =================
P2 = ROOT + r"\backtest\build_satellite_pool.py"
t2 = io.open(P2, encoding="utf-8").read()

anchor2 = "NAMES = json.load(open(BASE / \"data_full_names.json\", encoding=\"utf-8\"))"
assert anchor2 in t2
t2 = t2.replace(anchor2, anchor2 + '''
_nh = pd.read_csv(BASE / "data_fundamental" / "name_hist.csv", dtype={"code": str}).sort_values("TRADE_DATE").groupby("code").tail(1)
_name = _nh.set_index("code")["SECURITY_NAME_ABBR"].astype(str)
TUI_SET = set(_name[_name.str.contains("退")].index)
ST_SET = set(_name[_name.str.contains("ST")].index)''', 1)

# B1. 轨A top 列表过滤（signal_ln_atr 已过滤，此处防御性再过一遍）
old_a2 = "ln_top, ln_df = g[\"signal_ln_atr\"]({})"
assert old_a2 in t2
t2 = t2.replace(old_a2, "ln_top, ln_df = g[\"signal_ln_atr\"]({})\nln_top = [c for c in ln_top if c not in TUI_SET]", 1)

# B2. 轨B：过滤 ST/退 + 补足 20
old_b2 = """ok = np.where(np.isfinite(sc_row) & gb["ELIG_A4"][di])[0]
ok = sorted(ok, key=lambda j: -sc_row[j])[:20]"""
assert old_b2 in t2, "pool a4d block missing"
new_b2 = """ok = np.where(np.isfinite(sc_row) & gb["ELIG_A4"][di])[0]
ok = sorted(ok, key=lambda j: -sc_row[j])
ok = [j for j in ok if gb["codes"][j] not in ST_SET and gb["codes"][j] not in TUI_SET][:20]"""
t2 = t2.replace(old_b2, new_b2, 1)

# B3. 卡片注释更新过滤口径
t2 = t2.replace('"note": "安慰剂500 p=0.0000 · 与FB3相关-0.165 · slip50稳健 · fwd段制交叉验证方向一致"',
                '"note": "安慰剂500 p=0.0000 · 与FB3相关-0.165 · slip50稳健 · 已排除退市整理期\\"退\\"（回测零成本；全排ST减收益7.3pp故保留ST）"', 1)
t2 = t2.replace('"note": "相位中位1.075 · 安慰剂500 p=0.000 · DSR 0.987 · slip50稳健"',
                '"note": "相位中位1.075 · 安慰剂500 p=0.000 · DSR 0.987 · 已过滤 ST/*ST/退（回测 +3.2pp/回撤 -2.5pp/相位一致改善）"', 1)
io.open(P2, "w", encoding="utf-8").write(t2)
print("build_satellite_pool: 过滤+注释落地")
