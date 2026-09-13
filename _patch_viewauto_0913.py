# -*- coding: utf-8 -*-
"""view-auto 三轨化补丁（v2：文本块来自独立文件，避免 heredoc 引号嵌套）"""
import io

SRC = r"D:\Documents\Workbuddy\股票基金\quant-weight-system\build_dual_system.py"
t = io.open(SRC, encoding="utf-8").read()

# 1. 导航
old_nav = '["sys-auto","🅰️","全量池中/长线",[["card-tbl-v9","标的汇总表"],["card-tbl-v9-detail","逐标的详情"],["watch-v9-card","中长线跟踪"]]],'
assert old_nav in t, "nav missing"
t = t.replace(old_nav,
  '["sys-auto","🛰️","三轨中长线",[["sat-card","双卫星目标持仓"],["fb3-pool-card","FB3 基金池"],["card-tbl-v9","v9 历史池(退役)"],["watch-v9-card","历史跟踪(退役)"]]],', 1)

# 2. view-auto 标题与注释
old_sub = '"🅰️ 全量池中/长线", "auto", "全市场自动池 · 股票分层+基金",'
assert old_sub in t, "sub missing"
t = t.replace(old_sub, '"🛰️ 三轨中长线", "auto", "FB3-H20 主仓 + 冷门低波/A4D 双卫星（v9 战法已退役，下表仅历史留档）",', 1)
old_note = '"档位变化对比上次再平衡（07-23）· 建议动作 = 当前档位下的操作指引 · 回测参考在监控总览视图",'
assert old_note in t, "note missing"
t = t.replace(old_note, '"⛔ 下方 v9 表为已退役战法的历史留档（2026-09-13 十重证伪），现行三轨体系见上方双卫星卡与 FB3 基金池卡",', 1)

# 3. FB3 池卡（插在 WATCH_V9_CARD 定义前）——三引号用 3*单引号拼接避免嵌套
Q3 = chr(39) * 3
anchor = "WATCH_V9_CARD = f" + Q3 + '<div class="card" id="watch-v9-card">'
assert anchor in t, "watch anchor missing"
fb3 = (
    "_sp_j = json.load(open(BASE / \"short_pool.json\", encoding=\"utf-8\"))\n"
    "_fund_tier = _sp_j.get(\"tiers\", {}).get(\"fund\", [])\n"
    "_mg = _sp_j.get(\"market_gate\", {})\n"
    "_fund_rows = \"\"\n"
    "for _c in _fund_tier:\n"
    "    _d = _sp_j.get(\"details\", {}).get(_c, {})\n"
    "    _fund_rows += (f'<tr><td><code>{_c}</code></td><td>{_d.get(\"name\", \"\")}</td>'\n"
    "                   f'<td class=\"num\">{_d.get(\"score\", \"—\")}</td><td>{_d.get(\"pool\", \"fund\")}</td></tr>')\n"
    "_gate_txt = (\"🟢 开\" if _mg.get(\"open\") else \"🔴 关（熊市防守：FB3 转 Top3 低波仓）\") + f' · 沪深300 {_mg.get(\"idx_close\", \"—\")} vs MA20 {_mg.get(\"idx_ma20\", \"—\")}'\n"
    "FB3_POOL_CARD = (f'<div class=\"card\" id=\"fb3-pool-card\">'\n"
    "                 f'<h2>🥇 主仓 FB3-H20 基金池 <span class=\"badge badge-auto\">当前 regime 持仓 · 数据截至 {_sp_j.get(\"as_of\", \"—\")}</span></h2>'\n"
    "                 f'<div class=\"sub\">市况门控 {_gate_txt} · 60% 资金 · 牛市 Top10 动量 / 熊市 Top3 低波（C 类份额，T+1 净值申赎）</div>'\n"
    "                 f'<div class=\"tbl-wrap\"><table class=\"tbl\"><thead><tr><th>代码</th><th>名称</th><th>动量分</th><th>池</th></tr></thead><tbody>{_fund_rows or \"<tr><td colspan=4>空（门控关闭）</td></tr>\"}</tbody></table></div></div>')\n\n"
)
t = t.replace(anchor, fb3 + anchor, 1)

# 4. extra_card 挂 FB3
t = t.replace("  extra_card=WATCH_V9_CARD + SAT_CARD,", "  extra_card=SAT_CARD + FB3_POOL_CARD + WATCH_V9_CARD,", 1)

io.open(SRC, "w", encoding="utf-8").write(t)
print("view-auto 三轨化写盘完成")
