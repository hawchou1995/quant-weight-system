# -*- coding: utf-8 -*-
"""把 targets() 收敛成单一扫描出口 scan()（返回 {targets, tables}），并暴露给诊断用。

动机：覆盖/诊断脚本此前各自复制了一份判据 → 改完源码数字不变（本会话第二次同型坑）。
现在唯一真源是 scan()，诊断只读它的输出。
"""
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
        FAIL.append(f"[{tag}] 命中 {n} != {cnt}")
        return
    s = s.replace(old, new, 1 if cnt == 1 else cnt)


rep("""  function targets(){
    var out = [], tbs = document.querySelectorAll('table.tbl');""",
    """  /* 单一扫描出口：targets=可刷单元格；tables=逐表诊断信息（供覆盖率/排错脚本读取，
     避免诊断脚本自己复制一份判据 —— 那是本会话踩过两次的坑） */
  function scan(){
    var out = [], info = [], tbs = document.querySelectorAll('table.tbl');""", 1, "scan-head")

rep("""      if (!ths.length) continue;
      var pxI = -1, pcI = -1;""",
    """      if (!ths.length) continue;
      var tid = tb.id || tb.getAttribute('data-t') || '(无id)';
      var nRows = tb.querySelectorAll('tbody tr').length;
      var pxI = -1, pcI = -1;""", 1, "scan-tid")

rep("""      if (pxI < 0 && pcI < 0) continue;""",
    """      if (pxI < 0 && pcI < 0) { info.push({id: tid, rows: nRows, elig: 0, skip: '无价格/涨跌列'}); continue; }""",
    1, "scan-skip1")

rep("""      if (/浮盈|盈亏|市值|净值/.test(hdrAll)) continue;
      if (pcI < 0 && /权重/.test(hdrAll)) continue;
      var trs = tb.querySelectorAll('tbody tr');""",
    """      if (/浮盈|盈亏|市值|净值/.test(hdrAll)) {
        info.push({id: tid, rows: nRows, elig: 0, skip: '估值表(浮盈/盈亏/市值/净值)'}); continue;
      }
      if (pcI < 0 && /权重/.test(hdrAll)) {
        info.push({id: tid, rows: nRows, elig: 0, skip: '估值表(权重列且无涨跌幅列)'}); continue;
      }
      var trs = tb.querySelectorAll('tbody tr');
      var nElig = 0;""", 1, "scan-skip2")

rep("""        out.push({tr: tr, tb: tb, code: code, name: name,
                  px: pxI >= 0 && tds[pxI] ? tds[pxI] : null,
                  pct: pcI >= 0 && tds[pcI] ? tds[pcI] : null});
      }
    }
    return out;
  }""",
    """        out.push({tr: tr, tb: tb, code: code, name: name,
                  px: pxI >= 0 && tds[pxI] ? tds[pxI] : null,
                  pct: pcI >= 0 && tds[pcI] ? tds[pcI] : null});
        nElig++;
      }
      info.push({id: tid, rows: nRows, elig: nElig, skip: nElig ? '' : '行内无代码'});
    }
    return {targets: out, tables: info};
  }
  function targets(){ return scan().targets; }""", 1, "scan-tail")

rep("""  window.INTRADAY = {refresh: refresh, applyQuotes: applyQuotes, targets: targets, state: S, __fetchPool: fetchPool,""",
    """  window.INTRADAY = {refresh: refresh, applyQuotes: applyQuotes, targets: targets, state: S,
                     __scan: scan, __fetchPool: fetchPool,""", 1, "expose-scan")

p.write_text(s, encoding="utf-8")
print("\n=== 失败项 ===" if FAIL else "\n✅ scan() 收敛补丁命中")
for f in FAIL:
    print(" ", f)
sys.exit(1 if FAIL else 0)
