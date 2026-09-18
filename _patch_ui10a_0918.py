# -*- coding: utf-8 -*-
"""#10 第二步（皮肤层）补丁 A：公共 UI 层扁平化 + 导航 hover 下拉。

扁平控制台基线（对齐 gushi 参考站）：
  圆角收敛 16/20px → 6/4px ｜ 渐变→纯色 ｜ 阴影只留给浮层 ｜ 密度提升 ｜ 数字等宽
所有替换均带计数断言（命中数不符即报错退出，不静默改错）。
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
FAIL = []


def rep(txt, old, new, cnt=1, tag=""):
    n = txt.count(old)
    if n != cnt:
        FAIL.append(f"[{tag}] 期望 {cnt} 处，实际 {n} 处：{old[:60]!r}")
        return txt
    return txt.replace(old, new)


# ============================ A. ui_components.py ============================
p = ROOT / "ui_components.py"
s = p.read_text(encoding="utf-8")
o = s

# --- A1 设计令牌（圆角/墨色/等宽字体） ---
s = rep(s, """  --nav-bg:#ffffff; --shadow:0 1px 3px rgba(0,0,0,.08);
}""", """  --nav-bg:#ffffff; --shadow:0 1px 3px rgba(0,0,0,.08);
  /* #10 皮肤层（2026-09-18）：扁平控制台令牌 —— 圆角收敛 / 密度提升 / 数字等宽 */
  --r:6px; --r-sm:4px; --accent-ink:#20160a;
  --mono:ui-monospace,'SF Mono',Menlo,Consolas,'Liberation Mono',monospace;
}""", 1, "A1-tokens")

# --- A2 body 字号基线（13px 控制台密度） ---
s = rep(s, "body{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;background:var(--bg);color:var(--text);margin:0;transition:background .2s,color .2s}",
        "body{font-family:-apple-system,'PingFang SC','Microsoft YaHei','Segoe UI',sans-serif;font-size:13px;line-height:1.6;"
        "background:var(--bg);color:var(--text);margin:0;-webkit-font-smoothing:antialiased;transition:background .2s,color .2s}", 1, "A2-body")

# --- A3 顶栏：高度 56→52 + logo 字号 ---
s = rep(s, "z-index:900;height:56px;background:#1b2130;", "z-index:900;height:52px;background:#1b2130;", 1, "A3-topbar-h")
s = rep(s, "body{padding-top:56px}", "body{padding-top:52px}", 1, "A3-body-pt")
s = rep(s, ".topbar .logo{font-size:17px;font-weight:700;", ".topbar .logo{font-size:15px;font-weight:700;", 1, "A3-logo-fs")

# --- A4 去渐变：logo 方块 / 社区按钮 / 激活 tab ---
s = rep(s, "background:linear-gradient(135deg,#f59e0b,#ef4444);display:inline-block}",
        "background:var(--accent);display:inline-block}", 2, "A4-dot-gradient")
s = rep(s, """.community{display:inline-block;padding:6px 14px;border-radius:20px;
  background:linear-gradient(135deg,#FF9A3D 0%,#F2701D 100%);color:#fff;text-decoration:none;font-weight:600;font-size:13px}""",
        """.community{display:inline-block;padding:6px 12px;border-radius:var(--r);border:1px solid rgba(255,255,255,.16);
  background:rgba(255,255,255,.10);color:#fff;text-decoration:none;font-weight:500;font-size:12.5px}
.community:hover{background:rgba(255,255,255,.18)}""", 1, "A4-community")
s = rep(s, ".sidenav a.active{background:linear-gradient(135deg,#FF9A3D 0%,#F2701D 100%);color:#fff;font-weight:600}",
        ".sidenav a.active{background:rgba(255,255,255,.10);color:#fff;font-weight:600;box-shadow:inset 0 -2px 0 var(--accent)}", 1, "A4-nav-active")
s = rep(s, ".fbar .fill{height:100%;border-radius:6px;background:linear-gradient(90deg,#3b82f6,#f59e0b)}",
        ".fbar .fill{height:100%;border-radius:var(--r-sm);background:var(--accent)}", 1, "A4-fbar")

# --- A5 按钮/输入：圆角收敛 ---
s = rep(s, """  padding:6px 14px;font-size:13px;cursor:pointer;font-family:inherit;display:inline-flex;align-items:center;gap:6px}""",
        """  padding:6px 12px;font-size:12.5px;cursor:pointer;font-family:inherit;display:inline-flex;align-items:center;gap:6px}""", 1, "A5-tbbtn")
s = rep(s, ".tb-btn{background:var(--card2);border:1px solid var(--border);color:var(--text);border-radius:20px;",
        ".tb-btn{background:var(--card2);border:1px solid var(--border);color:var(--text);border-radius:var(--r);", 1, "A5-tbbtn-r")

# --- A6 侧栏 tab：圆角/内边距/空图标不占位 ---
s = rep(s, ".sidenav a{display:inline-flex;align-items:center;gap:8px;padding:8px 14px;border-radius:9px;",
        ".sidenav a{display:inline-flex;align-items:center;gap:8px;padding:7px 12px;border-radius:var(--r);", 1, "A6-nav-a")
s = rep(s, ".sidenav a .ic{font-size:16px;width:20px;text-align:center}",
        ".sidenav a .ic{font-size:16px;width:20px;text-align:center}\n.sidenav a .ic:empty,.sidenav a .ic:blank{display:none}", 1, "A6-nav-ic")

# --- A7 子导航：hover 下拉（替换"暂收起"占位实现） ---
s = rep(s, """/* 子章节下拉暂收起（gushi 无子导航；内容一张不丢，只在视图内）。下一轮补 hover 下拉 */
.sidenav .sn-sub{display:none;margin:0;flex-direction:row;gap:2px}
.sidenav .sn-sub.collapsed{display:none}
.sidenav .sn-arrow{margin-left:auto;font-size:10px;color:var(--faint)}
.sidenav .sn-sub a{padding:5px 10px;font-size:12px;color:var(--sub);border-radius:8px;font-weight:400}
.sidenav .sn-sub a .dot-sub{width:4px;height:4px;border-radius:50%;background:var(--line);flex:none}
.sidenav .sn-sub a:hover{color:var(--text);background:var(--card2)}
.sidenav .sn-sub a.active{color:var(--accent);font-weight:600;background:rgba(245,158,11,.08)}""",
        """/* 子章节 hover 下拉（2026-09-18 #10 皮肤层）：每个 tab 由 JS 包在 .sn-grp 定位容器里 */
.sn-grp{position:relative;display:flex;align-items:center;height:52px}
.sidenav .sn-sub{display:none;position:absolute;top:100%;left:0;min-width:154px;margin:0;padding:5px;
  flex-direction:column;gap:1px;background:#232a36;border:1px solid rgba(255,255,255,.10);
  border-radius:0 0 var(--r) var(--r);box-shadow:0 10px 24px rgba(0,0,0,.30);z-index:960}
.sn-grp:hover .sn-sub{display:flex}
.sidenav .sn-arrow{margin-left:2px;font-size:10px;color:rgba(255,255,255,.42)}
.sn-grp:hover .sn-arrow{color:#fff}
.sidenav .sn-sub a{padding:6px 10px;font-size:12.5px;color:rgba(255,255,255,.72);border-radius:var(--r-sm);
  font-weight:400;white-space:nowrap}
.sidenav .sn-sub a .dot-sub{width:4px;height:4px;border-radius:50%;background:rgba(255,255,255,.32);flex:none}
.sidenav .sn-sub a:hover{color:#fff;background:rgba(255,255,255,.10)}
.sidenav .sn-sub a.active{color:#fff;font-weight:600;background:rgba(255,255,255,.10);box-shadow:none}""", 1, "A7-snsub")

# --- A8 开市徽章：圆角收敛 ---
s = rep(s, "  padding:4px 11px;border-radius:20px;border:1px solid transparent;white-space:nowrap}",
        "  padding:3px 9px;border-radius:var(--r-sm);border:1px solid transparent;white-space:nowrap}", 1, "A8-mktbadge")

# --- A9 卡片：圆角 16→6 + 内边距压缩 + 标题字号 ---
s = rep(s, ".card{background:var(--card);border-radius:16px;padding:22px;margin-bottom:22px;border:1px solid var(--border);overflow-x:auto}",
        ".card{background:var(--card);border-radius:var(--r);padding:16px 18px 18px;margin-bottom:12px;border:1px solid var(--border);overflow-x:auto}", 1, "A9-card")
s = rep(s, ".card h2{font-size:18px;margin:0 0 4px;display:flex;align-items:center;gap:10px}",
        ".card h2{font-size:15px;font-weight:600;margin:0 0 3px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}", 1, "A9-h2")
s = rep(s, ".card .sub{color:var(--sub);font-size:12px;margin-bottom:14px}",
        ".card .sub{color:var(--sub);font-size:12px;line-height:1.75;margin-bottom:12px}", 1, "A9-sub")

# --- A10 徽章：药丸→小方标；蓝徽章中性化 ---
s = rep(s, ".badge{font-size:11px;padding:2px 10px;border-radius:20px;font-weight:500}",
        ".badge{font-size:11px;padding:1px 6px;border-radius:var(--r-sm);font-weight:500;border:1px solid transparent;background:var(--card2);color:var(--sub);white-space:nowrap}", 1, "A10-badge")
s = rep(s, ".badge-auto{background:rgba(245,158,11,.15);color:#b45309}",
        ".badge-auto{background:rgba(245,158,11,.12);color:#b45309;border-color:rgba(245,158,11,.25)}", 1, "A10-badge-auto")
s = rep(s, ".badge-lite{background:rgba(59,130,246,.15);color:#1d4ed8}",
        ".badge-lite{background:var(--card2);color:var(--sub);border-color:var(--border)}", 1, "A10-badge-lite")
s = rep(s, '[data-theme="dark"] .badge-lite{color:#60a5fa}',
        '[data-theme="dark"] .badge-lite{background:var(--card2);color:var(--sub);border-color:var(--border)}', 1, "A10-badge-lite-dark")

# --- A11 KPI：圆角/字号/数字等宽 ---
s = rep(s, ".kpi{flex:1;min-width:128px;background:var(--card2);border-radius:12px;padding:12px 16px;border:1px solid var(--border)}",
        ".kpi{flex:1;min-width:122px;background:var(--card2);border-radius:var(--r);padding:10px 14px;border:1px solid var(--border)}", 1, "A11-kpi")
s = rep(s, ".kpi .v{font-size:22px;font-weight:700;margin-top:3px}",
        ".kpi .v{font-size:20px;font-weight:700;margin-top:2px;font-variant-numeric:tabular-nums}", 1, "A11-kpi-v")

# --- A12 工具条：圆角/内边距 ---
s = rep(s, "  border-radius:10px;padding:8px 12px;font-size:13px;width:220px;font-family:inherit}",
        "  border-radius:var(--r);padding:7px 11px;font-size:12.5px;width:210px;font-family:inherit}", 1, "A12-input")
s = rep(s, "  border-radius:10px;padding:8px 10px;font-size:13px;font-family:inherit}",
        "  border-radius:var(--r);padding:7px 9px;font-size:12.5px;font-family:inherit}", 1, "A12-select")
s = rep(s, ".toolbar .perm-group{display:flex;gap:4px;background:var(--card2);border:1px solid var(--border);border-radius:10px;padding:3px}",
        ".toolbar .perm-group{display:flex;gap:3px;background:var(--card2);border:1px solid var(--border);border-radius:var(--r);padding:3px}", 1, "A12-perm")
s = rep(s, ".toolbar .perm-group button{border:none;background:transparent;color:var(--sub);border-radius:8px;padding:5px 10px;font-size:12px;cursor:pointer;font-family:inherit}",
        ".toolbar .perm-group button{border:none;background:transparent;color:var(--sub);border-radius:var(--r-sm);padding:4px 9px;font-size:12px;cursor:pointer;font-family:inherit}", 1, "A12-permbtn")

# --- A13 表格：密度 + 数字等宽 + 数值列右对齐 ---
s = rep(s, "table.tbl{width:100%;border-collapse:collapse;font-size:13px}",
        "table.tbl{width:100%;border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums}", 1, "A13-tbl")
s = rep(s, "table.tbl th{background:var(--card2);color:var(--sub);font-size:12px;padding:10px 8px;border-bottom:2px solid var(--border);",
        "table.tbl th{background:var(--card2);color:var(--sub);font-size:11.5px;font-weight:600;padding:8px 8px;border-bottom:1px solid var(--border);", 1, "A13-th")
s = rep(s, "table.tbl td{padding:9px 8px;border-bottom:1px solid var(--line);vertical-align:middle}",
        "table.tbl td{padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:middle}\n"
        "table.tbl td.num,table.tbl th.num{text-align:right;font-family:var(--mono);font-size:12px}", 1, "A13-td")

# --- A14 药丸：药丸→方标 + 单色强度阶梯 ---
s = rep(s, """.pill{display:inline-block;padding:2px 10px;border-radius:20px;font-size:12px;font-weight:500}
.pill-full{background:rgba(220,38,38,.12);color:var(--up)}
.pill-add{background:rgba(234,88,12,.12);color:#ea580c}
.pill-watch{background:rgba(217,119,6,.12);color:#d97706}
.pill-cut{background:rgba(107,114,128,.15);color:var(--sub)}
.pill-clear{background:rgba(156,163,175,.15);color:var(--faint)}""",
        """.pill{display:inline-block;padding:1px 7px;border-radius:var(--r-sm);font-size:11.5px;font-weight:500;border:1px solid transparent}
.pill-full{background:rgba(220,38,38,.12);color:var(--up);border-color:rgba(220,38,38,.22)}
.pill-add{background:rgba(220,38,38,.06);color:var(--up);border-color:rgba(220,38,38,.16)}
.pill-watch{background:var(--card2);color:var(--sub);border-color:var(--border)}
.pill-cut{background:var(--card2);color:var(--faint);border-color:var(--border)}
.pill-clear{background:transparent;color:var(--faint);border-color:var(--border)}""", 1, "A14-pill")
s = rep(s, ".board-tag{font-size:11px;padding:1px 8px;border-radius:6px;",
        ".board-tag{font-size:11px;padding:1px 6px;border-radius:var(--r-sm);", 1, "A14-boardtag")

# --- A15 弹层/规则框/子 tab ---
s = rep(s, ".modal{background:var(--card);border-radius:16px;max-width:980px;width:100%;padding:24px;box-shadow:0 12px 48px rgba(0,0,0,.3)}",
        ".modal{background:var(--card);border-radius:8px;max-width:980px;width:100%;padding:20px;box-shadow:0 12px 48px rgba(0,0,0,.3)}", 1, "A15-modal")
s = rep(s, ".modal .m-head h3{margin:0;font-size:20px}", ".modal .m-head h3{margin:0;font-size:17px}", 1, "A15-modal-h3")
s = rep(s, ".modal .m-close{margin-left:auto;background:var(--card2);border:1px solid var(--border);color:var(--text);\n  width:34px;height:34px;border-radius:50%;cursor:pointer;font-size:16px}",
        ".modal .m-close{margin-left:auto;background:var(--card2);border:1px solid var(--border);color:var(--text);\n  width:30px;height:30px;border-radius:var(--r);cursor:pointer;font-size:14px}", 1, "A15-close")
s = rep(s, ".rule-box{background:var(--card2);border:1px solid var(--border);border-radius:12px;padding:13px 18px;margin-bottom:16px;font-size:13px;line-height:1.9;color:var(--sub)}",
        ".rule-box{background:var(--card2);border:1px solid var(--border);border-radius:var(--r);padding:12px 16px;margin-bottom:14px;font-size:12.5px;line-height:1.85;color:var(--sub)}", 1, "A15-rulebox")
s = rep(s, ".trade-tabs button{border:1px solid var(--border);background:var(--card2);color:var(--sub);border-radius:8px;",
        ".trade-tabs button{border:1px solid var(--border);background:var(--card2);color:var(--sub);border-radius:var(--r-sm);", 1, "A15-tradetabs")

# --- A16 顶栏按钮/主题按钮文案去 emoji ---
s = rep(s, '<button class="tb-btn" id="theme-btn" onclick="toggleTheme()">🌙 夜间</button>',
        '<button class="tb-btn" id="theme-btn" onclick="toggleTheme()">夜间</button>', 1, "A16-themebtn")
s = rep(s, '<a class="community" href="https://qingju.me/" target="_blank" rel="noopener">💬 青橘社区</a>',
        '<a class="community" href="https://qingju.me/" target="_blank" rel="noopener">青橘社区</a>', 1, "A16-community")
s = rep(s, "if(b)b.textContent=t==='dark'?'☀️ 日间':'🌙 夜间';", "if(b)b.textContent=t==='dark'?'日间':'夜间';", 1, "A16-themejs")

# --- A17 侧栏默认项 + 页脚链接去 emoji ---
s = rep(s, '''SIDENAV_ITEMS = [
    ("overview", "📊", "监控总览"),
    ("sys-auto", "🅰️", "全量池中/长线"),
    ("short", "⚡", "全量池短线"),
    ("table", "📋", "标的监控表"),
]''', '''SIDENAV_ITEMS = [
    ("overview", "", "监控总览"),
    ("sys-auto", "", "全量池中/长线"),
    ("short", "", "全量池短线"),
    ("table", "", "标的监控表"),
]''', 1, "A17-sidenav-items")
s = rep(s, """  var _foot='<a href="javascript:void(0)" data-anchor="review"><span class="ic">📋</span>复盘日志</a>'+
    '<a href="javascript:void(0)" data-anchor="changelog"><span class="ic">📝</span>更新日志</a>'+""",
        """  var _foot='<a href="javascript:void(0)" data-anchor="review">复盘日志</a>'+
    '<a href="javascript:void(0)" data-anchor="changelog">更新日志</a>'+""", 1, "A17-foot")

# --- A18 JS：tab 外包 .sn-grp 定位容器 ---
s = rep(s, """    var ext=it[4];
    if(ext){""", """    var ext=it[4];
    html+='<div class="sn-grp">';
    if(ext){""", 1, "A18-grp-open")
s = rep(s, """      html+='</div>';}});
  var _foot=""", """      html+='</div>';}
    html+='</div>';});
  var _foot=""", 1, "A18-grp-close")

# --- A19 JS：去掉点击折叠子导航（改 hover 后语义重复） ---
s = rep(s, """      // 主项折叠/展开：只有重复点击当前激活主项才折叠切换；首次/切新视图一律展开
      else if(a.getAttribute('data-toggle')&&a.nextElementSibling&&a.nextElementSibling.classList.contains('sn-sub')){
        var grp=a.nextElementSibling;
        var curMain=nav.querySelector('a[data-anchor]:not([data-sub]).active');
        if(curMain&&curMain===a){grp.classList.toggle('collapsed');}
        else{grp.classList.remove('collapsed');}
      }
""", """      /* 子导航改 hover 下拉（2026-09-18 #10）：主项点击只切视图，不再折叠/展开 */
""", 1, "A19-toggle")

p.write_text(s, encoding="utf-8")
print(f"ui_components.py: {len(o)} → {len(s)} chars")

# ============================ B. kxmm_card.py ============================
p2 = ROOT / "kxmm_card.py"
s2 = p2.read_text(encoding="utf-8")
o2 = s2

s2 = rep(s2, ".kx-select{background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:8px;",
         ".kx-select{background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:var(--r-sm);", 1, "B1-kxselect")
s2 = rep(s2, ".kx-ind-card{border:1px solid var(--border);border-radius:10px;padding:8px 10px;cursor:pointer;",
         ".kx-ind-card{border:1px solid var(--border);border-radius:var(--r);padding:8px 10px;cursor:pointer;", 1, "B2-kxind")
s2 = rep(s2, ".kx-tabs,.kx-subtabs{display:inline-flex;border:1px solid var(--border);border-radius:10px;overflow:hidden}",
         ".kx-tabs,.kx-subtabs{display:inline-flex;border:1px solid var(--border);border-radius:var(--r);overflow:hidden}", 1, "B3-kxtabs")
s2 = rep(s2, ".kx-tab,.kx-subtab{padding:5px 14px;font-size:13px;cursor:pointer;background:var(--card);color:var(--sub);",
         ".kx-tab,.kx-subtab{padding:5px 12px;font-size:12.5px;cursor:pointer;background:var(--card);color:var(--sub);", 1, "B4-kxtab")
s2 = rep(s2, ".kx-tab.active,.kx-subtab.active{background:var(--accent);color:#fff;font-weight:600}",
         ".kx-tab.active,.kx-subtab.active{background:var(--accent);color:var(--accent-ink);font-weight:600}", 1, "B5-kxactive")
s2 = rep(s2, "#hm-card .hm-seg{display:inline-flex;background:var(--card2);border:1px solid var(--border);border-radius:10px;overflow:hidden}",
         "#hm-card .hm-seg{display:inline-flex;background:var(--card2);border:1px solid var(--border);border-radius:var(--r);overflow:hidden}", 1, "B6-hmseg")
s2 = rep(s2, "#hm-card .hm-btn.active{background:linear-gradient(135deg,#FF9A3D 0%,#F2701D 100%);color:#fff;font-weight:600}",
         "#hm-card .hm-btn.active{background:var(--accent);color:var(--accent-ink);font-weight:600}", 1, "B7-hmbtn")
s2 = rep(s2, '<h2>😨 恐贪指数 ', '<h2>恐贪指数 ', 1, "B8-fgtitle")
s2 = rep(s2, '<h2>🔥 市场热力图 ', '<h2>市场热力图 ', 1, "B9-hmtitle")

p2.write_text(s2, encoding="utf-8")
print(f"kxmm_card.py: {len(o2)} → {len(s2)} chars")

print("\n=== 失败项 ===" if FAIL else "\n✅ 补丁 A 全部命中")
for f in FAIL:
    print(" ", f)
sys.exit(1 if FAIL else 0)
