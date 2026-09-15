# -*- coding: utf-8 -*-
"""今日涨停全景卡 · 双池上卡（行插入法，避免整行引号匹配）"""
P = "build_dual_system.py"
s = open(P, encoding="utf-8").read()
ok = []

# 1) 池标签块：插在 st_html 行之后（按标记行定位）
POOL_BLOCK = '''
        # v1.3 双池标签（2026-09-15 用户需求：双池直接上全景卡）
        _pools = s.get("pools", []) or []
        _pt = []
        if "R20" in _pools:
            _pt.append('<span class="badge" style="background:rgba(5,150,105,.18);color:#34d399" '
                       f'title="池A 超跌：r20 {s.get("r20")}%（需 ≤-7.31%）">A·超跌</span>')
        if "ADX" in _pools:
            _pt.append('<span class="badge" style="background:rgba(37,99,235,.16);color:#60a5fa" '
                       f'title="池B 趋势：ADX {s.get("adx")}（需 ≥27.9）">B·趋势</span>')
        _pool_html = "".join(_pt) or '<span style="color:var(--faint)">—</span>'
'''
lines = s.split("\n")
idx = next(k for k, l in enumerate(lines) if 'st_html = "".join(st) or' in l and "_pool_html" not in l)
lines.insert(idx + 1, POOL_BLOCK)
s = "\n".join(lines)
ok.append("pool-block")

def rep(old, new, tag):
    global s
    assert old in s, f"MISS {tag}"
    s = s.replace(old, new, 1)
    ok.append(tag)

# 2) 行内插入单元格
rep('_pct_td(s.get("dist_high"), 1), _txt_td(tag), _txt_td(tier_badge),',
    '_pct_td(s.get("dist_high"), 1), _txt_td(_pool_html), _txt_td(tag), _txt_td(tier_badge),', "pool-inrow")

# 3) 表头加列
rep('("amt","成交额(亿)"),("relpos","相对位置"),("dist","空间%"),("hit","命中")',
    '("amt","成交额(亿)"),("relpos","相对位置"),("dist","空间%"),("pools","滤网池"),("hit","命中")', "pool-head")

# 4) 标题分池计数
rep('{len(zp_stocks)} 只 · 命中 {len(zp_hits)} 只',
    '{len(zp_stocks)} 只 · 双池命中 {len(zp_hits)} 只（池A {sum(1 for x in zp_hits if "R20" in (x.get("pools") or []))} · 池B {sum(1 for x in zp_hits if "ADX" in (x.get("pools") or []))}）', "pool-badge")

# 5) 命中标签措辞
rep('color:#34d399">✅ A5命中</span>', 'color:#34d399">✅ 双池命中</span>', "hit-tag")

# 6) 全景卡说明（整行替换，按前缀定位）
NEW_SUB = ('<div class="sub">收盘涨幅 ≥9.5% 或封板标的（{zp_date} 收盘口径）· <b>✅ 双池命中</b> = 首板 + 非一字 + '
           'rel_pos≤0.5 + F3空间≥20% + 成交额≥5000万 + <b>池A 超跌（ret20≤-7.31%）/ 池B 趋势（ADX14≥27.9）至少命中其一</b>'
           '（v1.3 双池独立）· 滤网池列：A·超跌 / B·趋势（悬浮可见实测值）· 纯观察，不构成交易信号</div>')
lines = s.split("\n")
idx2 = next(k for k, l in enumerate(lines) if '收盘涨幅 ≥9.5% 或封板标的（{zp_date} 收盘口径）' in l)
lines[idx2] = NEW_SUB
s = "\n".join(lines)
ok.append("zp-sub")

open(P, "w", encoding="utf-8").write(s)
print("PATCHED:", ok)
