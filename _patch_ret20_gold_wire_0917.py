# -*- coding: utf-8 -*-
"""R-ret20-paper-0917 + R-gold-sat-0917 收尾接线
① daily_refresh 挂 ret20_paper 软步骤 + 状态文件入 git add 清单
② shadow_ret20 把当日臂清单写进 state.json（ret20_paper 的唯一信号来源，免去反读 metrics 末行）
③ build_dual_system 新增「ret20 倾斜臂模拟盘」卡 + 黄金/ret20 两卡挂进 sys-auto 导航
④ 黄金账本补「禁双计」口径（黄金袖账本与轨B 镜像同源，卫星层合计只取轨B，不得相加）
"""
import sys
import py_compile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OK = True


def patch(rel, old, new, tag):
    global OK
    p = BASE / rel
    t = p.read_text(encoding="utf-8")
    if new in t:
        print(f"  [skip] {tag}（已打过）")
        return
    if t.count(old) != 1:
        print(f"  [FAIL] {tag}：锚点命中 {t.count(old)} 次（期望 1）")
        OK = False
        return
    p.write_text(t.replace(old, new), encoding="utf-8")
    print(f"  [ok]   {tag}")


print("=" * 74)
print("P1 daily_refresh：挂 ret20_paper 软步骤 + git add 清单")
print("=" * 74)
patch("daily_refresh.py",
      '''    ("双卫星模拟盘 satellite_paper", ["backtest/satellite_paper_0914.py"], False),
''',
      '''    ("双卫星模拟盘 satellite_paper", ["backtest/satellite_paper_0914.py"], False),
    # ret20 倾斜臂模拟盘（R-ret20-paper-0917 · 2026-09-17 用户拍板 #2/#4「投产并加模拟盘」）
    # 形态：**不改生产 composite**（冻结引擎原样 = BASE）；λ0.2 / λ0.3 各以 68,000 **同额纯对照账户**落地，
    #       零实盘资金申领 → 逐日 A/B 可比、不与轨B 抢配额。信号唯一来源 = shadow_ret20/state.json 的当日臂清单。
    #       毕业首检 2026-10-15（NAV≥BASE 臂 / 月多数正 / 相对回撤≤BASE+5pp），过门后才由用户拍板给配额。
    # [软]=失败不阻断主链；--skip-ret20 跳过。
    ("ret20 倾斜臂模拟盘 ret20_paper[软]", ["backtest/ret20_paper.py"], "--skip-ret20" in sys.argv),
''', "P1a 步骤挂载")

patch("daily_refresh.py",
      '''                          "backtest/gold_sat_paper.json", "backtest/gold_sat_paper.py",
''',
      '''                          "backtest/gold_sat_paper.json", "backtest/gold_sat_paper.py",
                          "backtest/ret20_paper.py", "backtest/ret20_paper_l02.json", "backtest/ret20_paper_l03.json",
''', "P1b git add 清单")

print()
print("=" * 74)
print("P2 shadow_ret20：当日臂清单落 state.json（ret20_paper 的唯一来源）")
print("=" * 74)
patch("backtest/shadow_ret20.py",
      '''# 引擎锚文件（供研究侧 load_engine 自维护对齐；日链每次运行刷新）''',
      '''# 当日臂清单 + 信号日回写 state.json（R-ret20-paper-0917：ret20_paper.py 的唯一信号来源，
# 免去下游反读 daily_metrics.jsonl 末行这种隐式耦合；start_date/spec 保持不动。）
try:
    _st = json.load(open(STATE, encoding="utf-8")) if os.path.exists(STATE) else {}
    _st["last_signal_date"] = last_date
    _st["lists"] = {k: list(v) for k, v in lists.items()}
    _st["updated"] = last_date
    json.dump(_st, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log(f"[state] 臂清单回写 {STATE}（信号日 {last_date}）")
except Exception as _e:
    log(f"[state] 臂清单回写失败（{type(_e).__name__}: {_e}）——ret20_paper 退回读 metrics 末行")

# 引擎锚文件（供研究侧 load_engine 自维护对齐；日链每次运行刷新）''', "P2 state 回写")

print()
print("=" * 74)
print("P3 build_dual_system：ret20 倾斜臂模拟盘卡 + 两卡挂导航")
print("=" * 74)
patch("build_dual_system.py",
      '''GOLD_SAT_CARD = _gold_sat_card()''',
      '''GOLD_SAT_CARD = _gold_sat_card()


# ret20 倾斜臂模拟盘卡（R-ret20-paper-0917 · 2026-09-17 用户拍板 #2/#4「投产并加模拟盘」）
# 数据源：backtest/ret20_paper_l02.json / ret20_paper_l03.json（daily_refresh「ret20 倾斜臂模拟盘」软步骤产出）
#        + backtest/shadow_ret20/daily_metrics.jsonl（臂 NAV 与 TopN 重合度）
def _ret20_paper_card():
    import json as _js
    _arms = [("l02", "λ0.2", "#2 · 影子轨主候选"), ("l03", "λ0.3", "#4 · 影子轨陪跑")]
    try:
        _rows, _nav, _ovl = [], {}, {}
        for _a, _lab, _tagd in _arms:
            _p = BASE / "backtest" / f"ret20_paper_{_a}.json"
            _d = _js.loads(_p.read_text(encoding="utf-8"))
            _nh = _d.get("nav_history") or []
            _bs = float(_d["meta"].get("basis") or 68000.0)
            _nv = float((_nh[-1] or {}).get("nav") or _bs)
            _nav[_a] = _nv / _bs
            _rows.append((_a, _lab, _tagd, _nv / _bs, len(_d.get("positions") or {}),
                          float(_d.get("cash") or 0.0), _d["meta"].get("signal_date", "—"),
                          "运行中" if _nh else "待建仓"))
        try:
            _m = (BASE / "backtest" / "shadow_ret20" / "daily_metrics.jsonl").read_text(encoding="utf-8")
            _last = _js.loads(_m.strip().splitlines()[-1])
            _ovl = _last.get("overlap") or {}
            _nav["base"] = float((_last.get("nav") or {}).get("base") or 1.0)
        except Exception:
            pass
        _tr = "".join(
            f'<tr><td><b>{_lab}</b></td><td>{_tagd}</td><td>{_nv:.4f}</td><td>{_pn} 只</td>'
            f'<td>{_cs:.0f}</td><td>{_sg}</td><td>{_stt}</td></tr>'
            for _a, _lab, _tagd, _nv, _pn, _cs, _sg, _stt in _rows)
        _otxt = (f"λ0.2 与 BASE 重合 <b>{float(_ovl.get('l02_vs_base', 0)):.3f}</b> · "
                 f"λ0.3 与 BASE <b>{float(_ovl.get('l03_vs_base', 0)):.3f}</b> · "
                 f"λ0.2/λ0.3 互重合 <b>{float(_ovl.get('l02_vs_l03', 0)):.3f}</b>"
                 f"｜BASE 臂 NAV {_nav.get('base', 1.0):.4f}（同窗影子）") if _ovl else "影子 metrics 未就绪"
        return (f'<div class="card" id="ret20-paper-card">'
                f'<h2>📐 ret20 倾斜臂模拟盘（λ0.2 / λ0.3） <span class="badge badge-auto">2026-09-17 投产 · 生产 composite 未改</span></h2>'
                f'<div class="sub">形态：<code>l02=(z(comp)+0.2·z(ret20))/1.2</code>、<code>l03=(z(comp)+0.3·z(ret20))/1.3</code>'
                f'，冻结引擎 BASE 原样 = 生产口径 · 两臂各 <b>68,000 同额纯对照</b>（零实盘资金申领，不与轨B 抢配额）</div>'
                f'<table><thead><tr><th>臂</th><th>定位</th><th>NAV</th><th>在仓</th><th>现金</th><th>信号日</th><th>状态</th></tr></thead>'
                f'<tbody>{_tr}</tbody></table>'
                f'<div class="sub">{_otxt}</div>'
                f'<div class="sub" style="color:#b45309">⚠ 样本外记录 = 0 天（研究侧读数 λ0.2 off0 +25.08%/S1.411/50bp 19.25；'
                f'λ0.3 +24.36%/S1.376/50bp 18.67；安慰剂 p 均 0.05）→ 毕业首检 <b>2026-10-15</b>：'
                f'① NAV ≥ BASE 臂 ② 月度多数为正 ③ 相对回撤 ≤ BASE+5pp</div>'
                f'<div class="sub" style="color:var(--faint)">账本 backtest/ret20_paper_l02.json / ret20_paper_l03.json；'
                f'信号源 backtest/shadow_ret20/state.json。每日链内刷新。</div></div>')
    except Exception as _e:
        return (f'<div class="card" id="ret20-paper-card"><h2>📐 ret20 倾斜臂模拟盘</h2>'
                f'<div class="sub">ret20_paper_l02/l03.json 未生成（{_e}）→ 运行 backtest/ret20_paper.py</div></div>')


RET20_PAPER_CARD = _ret20_paper_card()''', "P3a 卡片定义")

patch("build_dual_system.py", '''{GOLD_SAT_CARD}''', '''{GOLD_SAT_CARD}
{RET20_PAPER_CARD}''', "P3b 卡片挂载")

patch("build_dual_system.py",
      '''["sat-card","卫星目标持仓"],["sat-paper-b-card","轨B 模拟盘（主轨）"],["fund-paper-card","基金主仓模拟盘"],["fb3-pool-card","FB3 基金池"]''',
      '''["sat-card","卫星目标持仓"],["sat-paper-b-card","轨B 模拟盘（主轨）"],["gold-sat-card","黄金卫星叠加"],["ret20-paper-card","ret20 倾斜臂模拟盘"],["fund-paper-card","基金主仓模拟盘"],["fb3-pool-card","FB3 基金池"]''',
      "P3c 导航列表")

print()
print("=" * 74)
print("P4 黄金账本补「禁双计」口径")
print("=" * 74)
_g = BASE / "backtest" / "gold_sat_paper.json"
_d = _g.read_text(encoding="utf-8")
if "禁双计" in _d:
    print("  [skip] P4（已打过）")
else:
    _d = _d.replace('"note": "叠加式 r_sat=(1−w)·r_B+w·r_gold；替轨B 的 10%，卫星总敞口仍 = CAP_B"',
                    '"note": "叠加式 r_sat=(1−w)·r_B+w·r_gold；替轨B 的 10%，卫星总敞口仍 = CAP_B",\n'
                    '  "sum_rule": "⛔ 禁双计：黄金腿已镜像进轨B positions，卫星层合计净值**只取轨B**；'
                    '本账本仅为黄金袖的分解视图（看 ΔS / 占比漂移），不得与轨B 相加"')
    _g.write_text(_d, encoding="utf-8")
    print("  [ok]   P4 sum_rule")

print()
print("=" * 74)
print("编译校验")
print("=" * 74)
for rel in ("daily_refresh.py", "build_dual_system.py", "backtest/shadow_ret20.py",
            "backtest/ret20_paper.py", "backtest/gold_sat_paper.py"):
    try:
        py_compile.compile(str(BASE / rel), doraise=True)
        print(f"  [ok] {rel}")
    except Exception as e:
        OK = False
        print(f"  [FAIL] {rel}: {type(e).__name__}: {e}")

print()
print("总结论：" + ("✅ 全部落地" if OK else "❌ 存在 FAIL"))
sys.exit(0 if OK else 1)
