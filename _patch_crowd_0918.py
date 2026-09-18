# -*- coding: utf-8 -*-
"""#11 第一步：晴雨视图注入点 + 大盘拥挤度卡（2026-09-18 用户需求）。

拥挤度口径（代理，Q3 已批准「先用可得代理指标顶上」）——全部来自已有产物，不新建数据依赖：
  ① 量能分位 45%：沪深300 成交量 20 日历史分位（index_000300.csv 的 volume 列）
  ② 趋势乖离 35%：沪深300 收盘相对 MA20 的乖离，±5% 线性映射到 0~100
  ③ 情绪温度 20%：kxmm 恐贪指数（kxmm_data.js 的 fear_greed.base.num）
  拥挤度 = 加权和（0~100）。高分 = 成交拥挤 + 指数偏离 + 情绪亢奋。
  定位：**风险提示指标，不是买卖信号**（与全站「仅客观展示」口径一致）。

同时给 KXMM_VIEW_HTML 加 `<!--KXMM_EXTRA-->` 占位符——后续把「市场晴雨表」卡
物理搬进同一视图时复用它（不用再动 kxmm_card 的视图结构）。
"""
import ast
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
BD = BASE / "build_dual_system.py"
KX = BASE / "kxmm_card.py"
OK = True

HELPER = '''

def _crowding():
    """大盘拥挤度（代理口径 · 2026-09-18 用户需求 #11）。

    三成分全部来自已有产物（不新建数据依赖）：
      量能分位 45% — 沪深300 成交量 20 日分位（index_000300.csv volume 列）
      趋势乖离 35% — 沪深300 收盘相对 MA20 乖离，±5% 映射 0~100
      情绪温度 20% — kxmm 恐贪指数（kxmm_data.js fear_greed.base.num）
    定位：风险提示，不是买卖信号。
    """
    import csv as _csv
    out = {"score": None, "vol_pct": None, "bias": None, "fg": None, "n": 0}
    try:
        rows = []
        with open(BASE / "index_000300.csv", encoding="utf-8") as fh:
            for r in _csv.DictReader(fh):
                rows.append(r)
        rows = [r for r in rows if r.get("close")][-40:]
        out["n"] = len(rows)
        if len(rows) >= 25:
            vols = [float(r["volume"]) for r in rows[-20:]]
            hist = [float(r["volume"]) for r in rows]
            cur = vols[-1]
            out["vol_pct"] = round(sum(1 for v in hist if v <= cur) / len(hist) * 100, 1)
            closes = [float(r["close"]) for r in rows]
            ma20 = sum(closes[-20:]) / 20
            bias = (closes[-1] / ma20 - 1) * 100
            out["bias"] = round(bias, 2)
            out["bias_pct"] = round(max(0.0, min(100.0, (bias + 5) / 10 * 100)), 1)
    except Exception:
        pass
    try:
        _t = (BASE / "kxmm_data.js").read_text(encoding="utf-8")
        _j = json.loads(_t[_t.find("{"):_t.rfind("}") + 1])
        _fg = (_j.get("fear_greed") or {}).get("base") or {}
        out["fg"] = _fg.get("num")
        out["fg_txt"] = _fg.get("status_str")
    except Exception:
        pass
    try:
        if out["vol_pct"] is not None and out["bias_pct"] is not None:
            fg = out["fg"] if isinstance(out["fg"], (int, float)) else 50
            out["score"] = round(out["vol_pct"] * 0.45 + out["bias_pct"] * 0.35 + fg * 0.20, 1)
    except Exception:
        pass
    return out


_CROWD = _crowding()


def _crowd_card():
    """拥挤度卡 HTML（注入市场晴雨视图）。数据缺失时降级显示，不抛错。"""
    c = _CROWD
    if c.get("score") is None:
        return ('<div class="card" id="crowd-card"><h2>大盘拥挤度 <span class="badge badge-auto">数据不足</span></h2>'
                '<div class="sub">需要 ≥25 个交易日的 index_000300 记录；当前样本 '
                + str(c.get("n", 0)) + ' 条。</div></div>')
    s = c["score"]
    if s >= 80:
        lab, col, hint = "极度拥挤", "#ef4444", "量能与情绪同时亢奋，历史上此区间后波动放大"
    elif s >= 65:
        lab, col, hint = "偏拥挤", "#f59e0b", "成交活跃度高，注意追高风险"
    elif s >= 40:
        lab, col, hint = "中性", "#3b82f6", "量能与估值偏离均处常态区间"
    elif s >= 25:
        lab, col, hint = "偏冷清", "#10b981", "量能萎缩，留意流动性"
    else:
        lab, col, hint = "极度冷清", "#10b981", "成交与情绪双低，历史上多为底部区域特征"
    return (
        '<div class="card" id="crowd-card">'
        '<h2>大盘拥挤度 <span class="badge badge-auto" style="background:' + col + '22;color:' + col + '">'
        + lab + '</span></h2>'
        '<div class="sub">代理口径（非买卖信号）：<b>量能分位</b> 45%（沪深300 成交量 20 日分位）+ '
        '<b>趋势乖离</b> 35%（收盘 vs MA20，±5% 映射）+ <b>情绪温度</b> 20%（恐贪指数）</div>'
        '<div class="kpis">'
        '<div class="kpi"><div class="l">拥挤度</div><div class="v" style="color:' + col + '">'
        + f'{s:.1f}' + '</div><div class="s">0~100 · 越高越拥挤</div></div>'
        '<div class="kpi"><div class="l">量能分位</div><div class="v">' + f'{c["vol_pct"]:.1f}' + '</div>'
        '<div class="s">沪深300 成交量 20 日分位</div></div>'
        '<div class="kpi"><div class="l">趋势乖离</div><div class="v">' + f'{c["bias"]:+.2f}%' + '</div>'
        '<div class="s">收盘 vs MA20</div></div>'
        '<div class="kpi"><div class="l">情绪温度</div><div class="v">' + str(c.get("fg") if c.get("fg") is not None else "—")
        + '</div><div class="s">恐贪指数 · ' + str(c.get("fg_txt") or "—") + '</div></div>'
        '</div>'
        '<div class="sub" style="color:var(--faint)">' + hint + ' · 样本 ' + str(c["n"]) + ' 个交易日'
        '（index_000300）｜ 仅客观展示，不构成交易信号</div>'
        '</div>'
    )


_CROWD_CARD = _crowd_card()
'''


def main():
    global OK
    # ① build_dual_system.py 追加 helper（在 kxmm 导入之后，确保 BASE/json 可用）
    t = BD.read_text(encoding="utf-8")
    if "_crowd_card" in t:
        print("  [skip] helper 已存在")
    else:
        anchor = "def _mkt_status():"
        if t.count(anchor) != 1:
            print(f"  [FAIL] helper 锚点命中 {t.count(anchor)}")
            OK = False
        else:
            t = t.replace(anchor, HELPER.strip() + "\n\n\n" + anchor, 1)
            print("  [ok]   helper 已插入（_crowding / _crowd_card / _CROWD_CARD）")

    # ② 注入市场晴雨视图：KXMM_VIEW_HTML 的 <!--KXMM_EXTRA--> 占位符
    old = "{KXMM_VIEW_HTML}"
    new = '{KXMM_VIEW_HTML.replace("<!--KXMM_EXTRA-->", _CROWD_CARD)}'
    if new in t:
        print("  [skip] 注入")
    elif t.count(old) == 1:
        t = t.replace(old, new, 1)
        print("  [ok]   已注入 KXMM_EXTRA → 拥挤度卡")
    else:
        print(f"  [FAIL] 注入锚点命中 {t.count(old)}")
        OK = False
    try:
        ast.parse(t)
    except SyntaxError as e:
        print(f"  [FAIL] BD AST line {e.lineno}: {e.msg}")
        OK = False
        return 1
    BD.write_text(t, encoding="utf-8")

    # ③ kxmm_card.py 加占位符
    k = KX.read_text(encoding="utf-8")
    if "<!--KXMM_EXTRA-->" in k:
        print("  [skip] 占位符")
    else:
        tail = "</div>\n\"\"\"\n\n\nKXMM_CSS = KXMM_CSS +"
        if k.count(tail) == 1:
            k = k.replace(tail, "<!--KXMM_EXTRA-->\n</div>\n\"\"\"\n\n\nKXMM_CSS = KXMM_CSS +", 1)
            ast.parse(k)
            KX.write_text(k, encoding="utf-8")
            print("  [ok]   <!--KXMM_EXTRA--> 已插入 kxmm 视图")
        else:
            print(f"  [FAIL] 占位符锚点命中 {k.count(tail)}")
            OK = False

    print()
    print("总结论：" + ("✅ 落地" if OK else "❌ FAIL"))
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
