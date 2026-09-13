# -*- coding: utf-8 -*-
"""看板深改补丁 v2（2026-09-13 晚）：
① sys-auto 视图清除 v9 历史池/跟踪池（表清空+标题退役，JS guard 安全）
② SAT 卡表格结构对齐选股表格（toolbar 搜索/排序 + .tbl）
③ 新增 SAT_PAPER_CARD 模拟盘展示（读 satellite_paper.json）"""
import io
import json

SRC = r"D:\Documents\Workbuddy\股票基金\quant-weight-system\build_dual_system.py"
t = io.open(SRC, encoding="utf-8").read()

# ---- ① v9 表清空（system_block 传参 v9_items → 空表）----
old = "  v9_items, \"tbl-v9\", \"card-tbl-v9\","
assert old in t, "v9 items param missing"
t = t.replace(old, "  [], \"tbl-v9\", \"card-tbl-v9\",", 1)
# 表标题加退役徽章（system_block 内 h2 渲染 items len —— 找 sys-auto 块的 head_tags 追加）
old_tag = "'<span class=\"badge badge-auto\">筛池 = 全市场绝对规则 Top3 等权 · 月轮动</span>',"
assert old_tag in t
t = t.replace(old_tag, old_tag + "\n             '<span class=\"badge\" style=\"background:#ef4444;color:#fff\">⛔ 已退役 · 历史数据已清除（2026-09-13 十重证伪）</span>',", 1)

# ---- ② SAT_CARD 表格加 toolbar + data 属性（客户端搜索/排序）----
old_sat = 'f\'<div class="tbl-wrap"><table class="tbl"><thead><tr><th>代码</th><th>收盘</th><th>一手约</th><th>守卫</th></tr></thead><tbody>{tds}</tbody></table></div>\')'
assert old_sat in t, "sat table missing"
new_sat = ('f\'<div class="toolbar" id="sat-bar-{track}">'
           '<input type="text" class="sat-q" data-t="{track}" placeholder="🔍 搜索代码…" autocomplete="off">'
           '<select class="sat-sort" data-t="{track}"><option value="idx">清单序</option><option value="code">代码 ↑</option><option value="lot">一手成本 ↑</option></select>'
           '<span class="count sat-count" data-t="{track}"></span></div>\''
           '\n                f\'<div class="tbl-wrap"><table class="tbl sat-tbl" data-t="{track}"><thead><tr><th>代码</th><th>收盘</th><th>一手约</th><th>守卫</th></tr></thead><tbody>{tds}</tbody></table></div>\')')
t = t.replace(old_sat, new_sat, 1)
# _sat_rows 签名加 track 参数
t = t.replace("def _sat_rows(track):", "def _sat_rows(track):", 1)
t = t.replace('{_sat_rows("track_a")}\n{_sat_rows("track_b")}', '{_sat_rows("track_a")}\n{_sat_rows("track_b")}', 1)

# ---- ③ SAT_PAPER_CARD（在 SAT_CARD 定义后）----
anchor = "except Exception as _e:"
assert anchor in t
paper = '''_pap_f = BASE / "backtest" / "satellite_paper.json"
try:
    _pap = json.load(open(_pap_f, encoding="utf-8"))
    _pm = _pap.get("meta", {})
    _nh = _pap.get("nav_history", [])
    _npos = sum(len(v) for v in _pap.get("positions", {}).values())
    _nav = _nh[-1][1] if _nh else 1.0
    _ret = (_nav - 1) * 100
    SAT_PAPER_CARD = (f'<div class="card" id="sat-paper-card">'
                      f'<h2>🧪 双卫星模拟盘 <span class="badge badge-auto">起始 {_pm.get("started", "—")} · 6.8 万（轨A 3.4万+轨B 3.4万）</span></h2>'
                      f'<div class="kpis">'
                      f'<div class="kpi"><div class="l">模拟净值</div><div class="v">{_nav:.4f}</div><div class="s">期初 1.0</div></div>'
                      f'<div class="kpi"><div class="l">累计收益</div><div class="v" style="color:{ "#10b981" if _ret >= 0 else "#ef4444" }">{_ret:+.2f}%</div><div class="s">含成本口径</div></div>'
                      f'<div class="kpi"><div class="l">持仓标的</div><div class="v">{_npos}</div><div class="s">目标 30</div></div>'
                      f'<div class="kpi"><div class="l">状态</div><div class="v">{"运行中" if _nh else "待建仓"}</div><div class="s">{(_nh[-1][0] if _nh else _pap.get("events", [{}])[-1].get("date", "—"))}</div></div>'
                      f'</div>'
                      f'<div class="sub">成交回填：<code>holdings_satellite.json</code> + <code>satellite_paper.json</code>（fills/positions/nav_history）· 每日收盘跑 <code>signal_satellite_0913.py</code> 自动对账</div>'
                      f'<div class="sub" style="color:var(--faint)">{(_pap.get("events", [{}])[-1].get("event", ""))}</div>'
                      f'</div>')
except Exception as _e2:
    SAT_PAPER_CARD = (f'<div class="card" id="sat-paper-card"><h2>🧪 双卫星模拟盘</h2>'
                      f'<div class="sub">satellite_paper.json 未生成（{_e2}）</div></div>')

except Exception as _e:'''
t = t.replace(anchor, paper, 1)

# ---- ④ extra_card 挂模拟盘卡 + 移除 WATCH_V9 ----
t = t.replace("  extra_card=SAT_CARD + FB3_POOL_CARD + WATCH_V9_CARD,",
              "  extra_card=SAT_CARD + SAT_PAPER_CARD + FB3_POOL_CARD,", 1)

io.open(SRC, "w", encoding="utf-8").write(t)
print("看板深改补丁 v2 写盘完成")
