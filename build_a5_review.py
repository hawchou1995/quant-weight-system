# -*- coding: utf-8 -*-
"""
A5_tp8t2 实验系统 → 复盘日志（2026-08-28 投产，双轨方案 v1.1）
读 a5_pool.js（由 build_a5_pool.py 生成）→ 生成：
  review/review_a5.md      （覆盖式累积复盘：验证统计 + 三闸 + 持仓 + 已平仓 + 回避清单）
  review/a5_review.json    （结构化数据，供看板 view-review 分区渲染）

口径：模拟盘逐笔跟踪 net_ret（含成本），与 v9/短线池的信号级 T+1 复盘不同，故独立生成。
验证门基准 = 全部信号口径（46.1%/-0.17%/21.5%），与扫描器执行同口径。

用法：python build_a5_review.py    （收盘管道 refresh_daily.py 第 6 步调用）
"""
import os, json, time

BASE = os.path.dirname(os.path.abspath(__file__))
REVIEW_DIR = os.path.join(BASE, "review")
JS_F = os.path.join(BASE, "a5_pool.js")


def load_pool():
    if not os.path.exists(JS_F):
        return None
    txt = open(JS_F, encoding="utf-8").read()
    return json.loads(txt[len("window.A5_POOL = "):-1])


def pct(v, nd=2, sign=True):
    if v is None:
        return "—"
    s = "%+.2f%%" % v if sign else "%.2f%%" % v
    return s


def build():
    t0 = time.time()
    A = load_pool()
    if A is None:
        print("⚠ a5_pool.js 不存在，先运行 build_a5_pool.py")
        return None
    bench = A["bench"]
    stats = A["stats"]
    gate = A["gate"]
    as_of = A["as_of"]
    md = []
    md.append(f"# 🎯 打板实验（A5_tp8t2）模拟盘复盘 · {as_of}")
    md.append("")
    md.append("> **模拟盘边缘验证 · 非实盘指令** · 双轨方案 v1.1：A5_tp8t2 主模型模拟盘 + A2_tp3 回避清单（负期望警示，不单独交易）")
    md.append("> 口径：逐笔 net_ret（含成本买 0.525%/卖 0.625%）· 验证门基准 = **全部信号口径**（模拟盘无每日≤5/情绪门控，与执行同口径）")
    md.append("")
    md.append("## 📊 验证统计（vs 全部信号基准）")
    md.append("")
    md.append("| 指标 | 模拟盘 | 回测基准(全部信号) | 验证门 |")
    md.append("|---|---|---|---|")
    wr = stats["win_rate"]
    md.append(f"| 已平仓信号 | {stats['n']}/30 | 1,116 | 累计 30 触发判定 |")
    md.append(f"| 胜率 | {pct(wr, 1) if wr is not None else '—'} | {bench['win_rate']:.1f}% | [35%, 55%] {gate['wr']['note'] if gate['wr']['status']=='waiting' else ''} |")
    mn = stats["mean_net"]
    md.append(f"| 均值净收益 | {pct(mn) if mn is not None else '—'} | {bench['mean_net']:+.2f}% | >-0.5% {gate['mn']['note'] if gate['mn']['status']=='waiting' else ''} |")
    tp = stats["tp_ratio"]
    md.append(f"| tp 出场占比 | {pct(tp, 1) if tp is not None else '—'} | {bench['tp_ratio']:.1f}% | [12%, 32%] {gate['tp']['note'] if gate['tp']['status']=='waiting' else ''} |")
    nav = stats["nav"]
    md.append(f"| 净值（已平仓复利） | {nav:.4f} | —（组合复利 -72.2% 警示） | — |")
    md.append("")
    gwr, gmn, gtp = gate["wr"], gate["mn"], gate["tp"]
    md.append("### 🚦 验证门状态")
    md.append("")
    if gwr["status"] == "waiting":
        md.append(f"- ⏳ 信号不足（{stats['n']}/30）——{gwr['note']}")
    else:
        for name, g in (("胜率", gwr), ("均值净收益", gmn), ("tp占比", gtp)):
            flag = "✅" if g["status"] == "PASS" else "⛔"
            md.append(f"- {flag} {name}：{g['note']}")
    md.append(f"- **判定：{gate['verdict']}**")
    md.append("")
    md.append("> ⚠ **组合复利警示（回测）**：单笔算术期望为正（组合信号 +0.11%），但 10 年组合复利 **-72.2%/年化 -27.4%/回撤 -91.4%**——边缘太薄（σ≈5%/日），验证通过前只允许极小仓位（单笔≤1-2%）模拟，**禁止实盘**。")
    md.append("")
    md.append("## 💼 当前持仓")
    md.append("")
    if A["positions"]:
        md.append("| 代码 | 名称 | 入场日 | 入场价 | gap | 出场阶段 |")
        md.append("|---|---|---|---|---|---|")
        for p in sorted(A["positions"], key=lambda x: x.get("entry_date", "")):
            md.append(f"| {p['code']} | {p['name']} | {p['entry_date']} | {p['entry_px']:.2f} | "
                      f"{p['gap']*100:+.2f}% | T+{p.get('exit_stage',1)} |")
    else:
        md.append("（无）")
    md.append("")
    md.append("## 📜 已平仓（累计）")
    md.append("")
    if A["closed"]:
        md.append("| 代码 | 名称 | 入场日 | 出场日 | 入场价 | 出场价 | 原因 | 净收益 |")
        md.append("|---|---|---|---|---|---|---|---|")
        for p in A["closed"]:
            md.append(f"| {p['code']} | {p['name']} | {p['entry_date']} | {p['exit_date']} | "
                      f"{p['entry_px']:.2f} | {p['exit_px']:.2f} | {p['exit_reason']} | {pct(p['net_ret'])} |")
    else:
        md.append("（尚无平仓记录）")
    md.append("")
    md.append("## 📋 观察清单（今日首板，明日低开 2-5% 则入场）")
    md.append("")
    if A["watchlist"]:
        md.append("| 代码 | 名称 | 行业 | 首板日 | rel_pos | 成交额(万) |")
        md.append("|---|---|---|---|---|---|")
        for w in sorted(A["watchlist"], key=lambda x: -x.get("amt", 0)):
            md.append(f"| {w['code']} | {w['name']} | {w['ind']} | {w['sb_date']} | "
                      f"{w['rel_pos']:.2f} | {w['amt']/1e4:.0f} |")
    else:
        md.append("（无）")
    md.append("")
    md.append("## ⚠ A2_tp3 回避清单（负期望警示 · 不单独交易）")
    md.append("")
    md.append("今日满足 A2_tp3 信号（首板次日低开 2-6% + rel_pos≤0.7 + 成交额≥5000万）。回测胜率 63.1% 但单笔均值 -1.39%（负期望）→ 信号出现时回避或减仓，不追高。")
    md.append("")
    if A["avoid"]:
        md.append("| 代码 | 名称 | 行业 | 首板日 | 今日gap | rel_pos | 成交额(万) |")
        md.append("|---|---|---|---|---|---|---|")
        for a in sorted(A["avoid"], key=lambda x: -x.get("amt", 0)):
            md.append(f"| {a['code']} | {a['name']} | {a['ind']} | {a['sb_date']} | "
                      f"{a['gap']*100:+.2f}% | {a['rel_pos']:.2f} | {a['amt']/1e4:.0f} |")
    else:
        md.append("（无）")
    md.append("")
    md.append("---")
    md.append("*A5_tp8t2 实验系统 v1.1（含 A2_tp3 回避清单）· 口径见 spec_A5_tp8t2.md · 模拟盘仅供边缘验证，非实盘指令*")

    os.makedirs(REVIEW_DIR, exist_ok=True)
    md_f = os.path.join(REVIEW_DIR, "review_a5.md")
    open(md_f, "w", encoding="utf-8").write("\n".join(md))
    out = {
        "file": "review_a5.md", "as_of": as_of, "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "stats": stats, "gate": gate, "n_watch": len(A["watchlist"]),
        "n_avoid": len(A["avoid"]), "n_pos": len(A["positions"]), "n_closed": len(A["closed"]),
    }
    json.dump(out, open(os.path.join(REVIEW_DIR, "a5_review.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"✅ A5 复盘已生成 review/review_a5.md（as_of={as_of} · 已平仓 {len(A['closed'])} · "
          f"验证 {gate['verdict']} · 耗时 {time.time()-t0:.0f}s）")
    return out


if __name__ == "__main__":
    build()
