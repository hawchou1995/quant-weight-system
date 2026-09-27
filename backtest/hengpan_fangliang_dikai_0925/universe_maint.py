# -*- coding: utf-8 -*-
"""universe_maint.py — 股票池维护：清除「僵尸标的」并消除 live∩dead 重复列（2026-09-27，R-hpdk-pool-0927）

## 修的是什么（两个缺陷，一次修好）

**缺陷 1｜僵尸标的**：`universe.json`（「现存池」）里有 **18 只**标的最后一根**真实成交** K 线
早于阈值日（默认 2026-08-01）——早已退市或被吸收合并，却仍被当作现存股。
（sh600837 海通证券 2025-02-05 被国泰君安吸收、sh601989 中国重工 2025-08-12 被中国船舶吸收、
sz300391 长药退 2026-04-14 退市；另 7 只末次成交在 2004-2013，早于本策略窗口起点。）

**缺陷 2｜live ∩ dead 重复列（真 bug）**：`oos_run.py` 里 `syms = live + dead`，而
**11 只标的同时在 live 与 dead 中** ⇒ 面板里同一标的有**两列**、特征值相同 ⇒ 复合分相同 ⇒
**同一天可能被选两次，白占 K=10 里的名额**。
实测影响：2,595 个信号日中 **128 天（4.93%）** top-10 出现同日重复标的，**白占 131 个名额**；
两源（data_full vs delisted_bars）价格最大差 **6.93%**（sh600837，中位 1.39%）。

**关键巧合**：这 11 只**恰好全部**在那 18 只僵尸里 ⇒ **只从 live 移除这 18 只，两个缺陷同时消除**，
修复后面板列数 == 唯一标的数（5460 → 5442）。

## 为什么不把 7 只搬进 delisted_bars
`refresh_data.py:38` 对退市名录有 `end_date >= 2014-06-01` 的既定口径，这 7 只末次成交在 2004-2013，
**在该口径之外**；且全部早于本策略窗口起点，搬入既不必要、又会破坏「名录只含 2014+ 退市」的语义、
并把 data_full 的合成填充行带进 delisted_bars（该库现有合成行 = 0，应保持干净）。
⇒ 本脚本**只从 live 移除，不写 delisted_bars**。数据零丢失由下面的自检强制：
每一只被移除的标的，必须满足「已在 dead 中（bars 已存档）」或「末次真实成交 < 窗口起点（窗口内本就不交易）」。

## 做法（幂等、先备份、默认 dry-run）
1. 逐个 live 读 `data_full/<sym>.csv`，取最后一根**真实** bar（跳过合成行 `ohl==0 且 volume==0`）
2. `last_real < --thresh` ⇒ 僵尸；断言「在 dead 中」或「< 窗口起点」
3. 重写 `universe.json`：`universe` = live − 僵尸；`calendar`/`note` 不变；追加 `maint` 留痕
4. 自检：`live∩dead == 空`、`len(syms) == len(set(syms))`、剩余 live 无僵尸

用法:
  python universe_maint.py                 # dry-run（只报告）
  python universe_maint.py --apply         # 落盘（含备份）
"""
import argparse
import datetime as dt
import json
import pathlib
import shutil
import sys

import pandas as pd

R = pathlib.Path(__file__).resolve().parents[2]
UNI = R / "backtest/wechat_hotspot_leader_0925/universe.json"
DEADDIR = R / "backtest/_delisted_universe"
BARS = DEADDIR / "delisted_bars.csv.gz"
NAMES = R / "data_full_names.json"
DFULL = R / "data_full"
STAMP = dt.date.today().strftime("%Y%m%d")


def log(*a):
    print(*a, flush=True)


def last_real_bar(p):
    """返回 (末次真实成交日, 总行数, 合成行数)；缺失/不可解析 -> (None, 0, 0)。"""
    if not p.exists():
        return None, 0, 0
    try:
        d = pd.read_csv(p, usecols=["date", "open", "high", "low", "volume"])
    except Exception:
        return None, 0, 0
    n = len(d)
    syn = (d["open"] == 0) & (d["high"] == 0) & (d["low"] == 0) & (d["volume"] == 0)
    real = d.loc[~syn, "date"].astype(str).str.slice(0, 10)
    return (real.max() if len(real) else None), n, int(syn.sum())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--thresh", default="2026-08-01")
    a = ap.parse_args()

    U = json.loads(UNI.read_text(encoding="utf-8"))
    live = [u["sym"] for u in U["universe"]]
    cal = list(U["calendar"])
    win_start = cal[0]
    names = json.loads(NAMES.read_text(encoding="utf-8"))
    bars = pd.read_csv(BARS, usecols=["sym"])
    dead = sorted(bars["sym"].astype(str).unique().tolist())
    ovin = sorted(set(live) & set(dead))
    log("[in] live=%d dead=%d  面板列=%d  唯一=%d  重复列=%d"
        % (len(live), len(dead), len(live) + len(dead), len(set(live) | set(dead)),
           (len(live) + len(dead)) - len(set(live) | set(dead))))
    log("[in] live∩dead = %d 只: %s" % (len(ovin), ovin))
    log("[in] 窗口起点(日历首日) = %s" % win_start)

    rows, nofile = [], []
    for s in live:
        lr, n, nsyn = last_real_bar(DFULL / (s + ".csv"))
        (nofile if lr is None else rows).append(s) if lr is None else None
        if lr is not None and lr < a.thresh:
            rows.append((s, lr, n, nsyn)) if False else None
    # 上面的写法易错，改为显式循环
    rows, nofile = [], []
    for s in live:
        lr, n, nsyn = last_real_bar(DFULL / (s + ".csv"))
        if lr is None:
            nofile.append(s)
        elif lr < a.thresh:
            rows.append((s, lr, n, nsyn))
    zombies = [r[0] for r in rows]
    zset = set(zombies)
    log("\n[scan] 末次真实成交 < %s 的 live 标的 = %d 只 ; 文件缺失 = %d 只 %s"
        % (a.thresh, len(zombies), len(nofile), nofile[:5]))
    for s, lr, n, nsyn in sorted(rows, key=lambda x: x[1]):
        tag = "  [同时是 live∩dead]" if s in set(dead) else ""
        safe = "已存档于 dead" if s in set(dead) else ("窗口内不交易(%s<%s)" % (lr, win_start))
        log("   %-9s %-10s 末次真实成交 %s  行=%d 合成行=%d%s  -> %s"
            % (s, names.get(s, ""), lr, n, nsyn, tag, safe))
    log("\n[核对] live∩dead 的 %d 只是否全部属于僵尸: %s" % (len(ovin), set(ovin) <= zset))
    loss = [s for s, lr, _n, _x in rows if (s not in set(dead)) and (lr >= win_start)]
    log("[核对] 被移除但既不在 dead、末次成交又 >= 窗口起点的（=数据丢失风险）: %d %s"
        % (len(loss), loss))

    U2 = dict(U)
    U2["universe"] = [u for u in U["universe"] if u["sym"] not in zset]
    U2["maint"] = {
        "date": dt.date.today().isoformat(),
        "rule": "remove live syms whose last real (non-synthetic) bar < %s" % a.thresh,
        "removed_n": len(zombies), "removed_syms": zombies,
        "also_fixed": "live∩dead 重复列 %d 只（全部属于本次移除的僵尸）" % len(ovin),
        "dead_untouched": "delisted_bars.csv.gz / delisted_roster.csv 未改动",
        "why": ("两个缺陷一次修：① 僵尸标的（已退市/被吸收合并/长期停牌）不应留在现存池；"
                "② live-in-dead 重复列会让同一标的在面板里占两列、同日被选两次、白占 K=10 名额"),
        "evidence": "backtest/报告-复核-横盘低开策略-稳健性与数据核验-20260926.md §七",
    }
    live2 = [u["sym"] for u in U2["universe"]]

    ok_ov = not (set(live2) & set(dead))
    ok_uniq = (len(live2) + len(dead)) == len(set(live2) | set(dead))
    left = [s for s in live2 if (last_real_bar(DFULL / (s + ".csv"))[0] or "9999") < a.thresh]
    log("\n[check] 修复后 live=%d dead=%d 面板列=%d 唯一=%d"
        % (len(live2), len(dead), len(live2) + len(dead), len(set(live2) | set(dead))))
    log("[check] live∩dead 为空 : %s" % ok_ov)
    log("[check] 面板列数 == 唯一标的数 : %s（%d == %d）"
        % (ok_uniq, len(live2) + len(dead), len(set(live2) | set(dead))))
    log("[check] 剩余 live 中仍有僵尸的 : %d 只 %s" % (len(left), left[:5]))
    log("[check] 数据丢失风险 : %d 只" % len(loss))

    if not (ok_ov and ok_uniq and not left and not loss):
        log("\n!! 自检未通过 -> 不落盘")
        return 2
    if not a.apply:
        log("\n[dry-run] 未落盘。加 --apply 生效。")
        return 0

    shutil.copy2(UNI, UNI.parent / ("universe.json.bak-%s" % STAMP))
    UNI.write_text(json.dumps(U2, ensure_ascii=False), encoding="utf-8")
    log("\n[apply] 已落盘 universe.json : live %d -> %d（dead 未改动 %d 只）" % (len(live), len(live2), len(dead)))
    log("   备份 -> %s" % (UNI.parent / ("universe.json.bak-%s" % STAMP)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
