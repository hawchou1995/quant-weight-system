# -*- coding: utf-8 -*-
"""R-live 修正：① 名称提取取错列（守卫失效真因）② 标签语义（实时 vs 盘中）③ 药丸市况文案。"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
p = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system/intraday_live.py")
s = p.read_text(encoding="utf-8")
FAIL = []


def rep(old, new, cnt=1, tag=""):
    global s
    n = s.count(old)
    if n != cnt:
        FAIL.append(f"[{tag}] 期望 {cnt} 实际 {n}: {old[:70]!r}")
        return
    s = s.replace(old, new)


# ① 名称提取：第 0 列可能是代码列（卫星表）→ 取「去掉 6 位代码后仍非空」的第一个单元格；
#    优先用 data-search（A5 表自带，首词即名称）
rep("""        var tds = tr.children;
        if (!tds.length) continue;
        out.push({tr: tr, tb: tb, code: code,
                  name: (tds[0].textContent || '').replace(/\\d{6}/, '').replace(/\\s+/g, ' ').trim(),""",
    """        var tds = tr.children;
        if (!tds.length) continue;
        /* 名称：优先 data-search 首词；否则取「去掉 6 位代码后仍非空」的第一个单元格
           （卫星表第 0 列是代码列 → 必须跳到第 1 列的名称列，否则守卫拿到空名而失效） */
        var name = '';
        var ds = tr.getAttribute('data-search') || '';
        if (ds) name = ds.trim().split(/\\s+/)[0];
        if (!name) {
          for (var q = 0; q < tds.length && q < 3; q++) {
            var t2 = (tds[q].textContent || '').replace(/\\d{6}/g, '').replace(/[\\s\\-—%+.,()（）]/g, '');
            if (t2) { name = t2; break; }
          }
        }
        out.push({tr: tr, tb: tb, code: code, name: name,""", 1, "name-extract")

# ② th 标签 / 卡片徽章：盘中 → 实时
rep("""      '.live-th{margin-left:4px;font-size:10px;font-weight:500;color:#b45309;border:1px solid rgba(245,158,11,.35);',""",
    """      '.live-th{margin-left:4px;font-size:10px;font-weight:500;color:#b45309;border:1px solid rgba(245,158,11,.35);',""",
    1, "css-noop")
rep("""          var s2 = document.createElement('span'); s2.className = 'live-th'; s2.textContent = '盘中'; s2.title = CFG.TIP;""",
    """          var s2 = document.createElement('span'); s2.className = 'live-th'; s2.textContent = '实时'; s2.title = CFG.TIP;""",
    1, "th-label")
rep("""        bd.textContent = '盘中 ' + ts;""", """        bd.textContent = '实时 ' + ts;""", 1, "badge-label")
rep("""        var tx = (th.textContent || '').replace(/盘中/g, '').trim();""",
    """        var tx = (th.textContent || '').replace(/实时|盘中/g, '').trim();""", 2, "th-tx-strip")

# ③ 树图注释：盘中/非交易时段分开表述
rep("""        note.textContent = '盘中实时 · 更新于 ' + ts + '（全市场 ' + rows.length + ' 只）';""",
    """        note.textContent = (S.live ? '盘中实时' : '实时快照（非交易时段）') +
                           ' · 更新于 ' + ts + '（全市场 ' + rows.length + ' 只）';""", 1, "hm-note")

# ④ 药丸：市况 + 数据时间（含日期），非交易时段明确标注
rep("""    else if (S.idx) {
      parts.push('<span>' + S.idx.idxName + ' ' + (S.idx.idxPct > 0 ? '+' : '') + S.idx.idxPct.toFixed(2) + '%</span>');
      parts.push('<span class="sp">' + (S.live ? '盘中 ' : '最近 ') + (S.ts || '—') + '</span>');
    } else parts.push('<span class="sp">' + (S.err ? '通道不可用' : '待刷新') + '</span>');""",
    """    else if (S.idx) {
      parts.push('<span>' + S.idx.idxName + ' ' + (S.idx.idxPct > 0 ? '+' : '') + S.idx.idxPct.toFixed(2) + '%</span>');
      var t = S.mktTs || '';
      var stamp = t ? (t.slice(4, 6) + '-' + t.slice(6, 8) + ' ' + t.slice(8, 10) + ':' + t.slice(10, 12)) : (S.ts || '—');
      parts.push('<span class="sp">' + (S.live ? '盘中 ' + (S.ts || '') : '非交易时段 · 数据 ' + stamp) + '</span>');
    } else parts.push('<span class="sp">' + (S.err ? '通道不可用' : '待刷新') + '</span>');""", 1, "pill-text")

p.write_text(s, encoding="utf-8")
print("\n=== 失败项 ===" if FAIL else "\n✅ 修正补丁全部命中")
for f in FAIL:
    print(" ", f)
sys.exit(1 if FAIL else 0)
