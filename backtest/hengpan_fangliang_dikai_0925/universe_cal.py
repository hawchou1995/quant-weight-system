# -*- coding: utf-8 -*-
"""universe_cal.py — 推进 universe.json 的面板交易日历（2026-09-28，R-hpdk-cal-0928）

## 修的是什么（缩量超跌「数据未更新」的根因）
`backtest/wechat_hotspot_leader_0925/universe.json` 的 `calendar` 是缩量超跌族
（oos_run.py → hpdk_candidates.py → hpdk_paper.py）的**面板日历**：
  · `oos_run.py:load_universe()` 直接读它建面板（T = len(calendar)）
  · `hpdk_candidates.py:226` `T_last = cal[-1]` ⇒ 产物 `as_of`
  · `hpdk_paper.py` 同源
它由 `p1_universe.py` 依 `index_000300.csv` 一次性生成，**此后链路无任何日更步骤**
（`daily_refresh.py` 只跑 hpdk_candidates / hpdk_paper，不重建它）
⇒ 日历冻结在生成日（2026-09-28 实测冻结于 2026-09-24）
⇒ 缩量超跌卡片 as_of / buy_date 永不前进。
而云端 `cloud_refresh.py` 对 hpdk 三件套的新鲜度期望 = `index_000300.csv` 末行
⇒ 日日报 `stale(2026-09-24!=2026-09-28)`（2026-09-28 实测 3 条软失败）。

## 做法（最小侵入 · 单调 · 幂等）
只**追加** `index_000300.csv` 中晚于 `calendar[-1]` 的交易日：
  · 既有日历前缀逐位不变（面板历史不动 → 已封存决策 / A11 对拍基准不受影响）
  · 不动 `universe` 成员（不复活僵尸；`universe_maint.py` 的清除结果原样保留）
  · 追加前**校验新日期确有行情**（抽 20 只 live 标的，逐日要求 ≥80% 命中）
  · 幂等：已最新 → no-op；dry-run 默认，`--apply` 落盘（先备份 `universe.json.bak-cal-<ts>`）
  · 自检：新日历严格以旧日历为前缀 · 长度单调增 · 末日 == index 末日

## 为什么不是重跑 p1_universe.py
`p1_universe.py` 是**整池重建**：会复活 18 只僵尸标的（`universe_maint.py` 刚清掉的）、
丢弃 `maint` 留痕、重排 universe —— 超出「数据维护」边界
（预注册 §E-11 只允许「重新抓取退市股名录与行情」这一类）。

用法:
  python universe_cal.py            # dry-run（只报告）
  python universe_cal.py --apply    # 落盘（含备份）
"""
import argparse
import datetime as dt
import json
import pathlib
import shutil
import sys

R = pathlib.Path(__file__).resolve().parents[2]
UNI = R / "backtest/wechat_hotspot_leader_0925/universe.json"
IDX = R / "index_000300.csv"
DFULL = R / "data_full"
STAMP = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
COVER_MIN = 0.80          # 新日期在抽样标的中的最低命中率
SAMPLE_N = 20             # 抽样标的数


def log(*a):
    print(*a, flush=True)


def idx_dates():
    """index_000300.csv 的全部交易日（去重升序）；与 p1_universe.py 同源同口径。"""
    out = []
    for ln in IDX.read_text(encoding="utf-8-sig").splitlines():
        q = ln.split(",")[0].strip()
        if len(q) >= 10 and q[:4].isdigit() and q[4] == "-":
            out.append(q[:10])
    return sorted(set(out))


def sample_syms(uni):
    """抽 COVER_MIN 校验用的标的：live 中 data_full 文件存在的，按代码序取前 N。"""
    out = []
    for u in sorted(uni, key=lambda d: d["sym"]):
        if (DFULL / (u["sym"] + ".csv")).exists():
            out.append(u["sym"])
        if len(out) >= SAMPLE_N:
            break
    return out


def date_cover(sym, dates):
    """该标的文件里出现过的日期集合（只取 date 列，失败返回空集）。"""
    p = DFULL / (sym + ".csv")
    try:
        have = set()
        with p.open(encoding="utf-8", errors="replace") as fh:
            head = fh.readline().rstrip("\n").split(",")
            try:
                ci = head.index("date")
            except ValueError:
                ci = 0
            for ln in fh:
                parts = ln.split(",")
                if len(parts) > ci:
                    d = parts[ci].strip()[:10]
                    if d in dates:
                        have.add(d)
        return have
    except Exception:
        return set()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--uni", default=str(UNI))
    ap.add_argument("--index", default=str(IDX))
    a = ap.parse_args()

    uni_p = pathlib.Path(a.uni)
    if not uni_p.exists():
        log("[skip] universe.json 不存在：%s" % uni_p)
        return 0
    if not pathlib.Path(a.index).exists():
        log("[skip] index_000300.csv 不存在：%s（无权威日历 → 不推进）" % a.index)
        return 0

    U = json.loads(uni_p.read_text(encoding="utf-8"))
    old = list(U.get("calendar") or [])
    if not old:
        log("!! universe.json 无 calendar → 不处理（应重跑 p1_universe.py）")
        return 2

    idx = idx_dates()
    if not idx:
        log("[skip] index_000300.csv 无可用日期行 → 不推进")
        return 0
    new_dates = [d for d in idx if d > old[-1]]
    log("[in] universe.json calendar: %s → %s（n=%d）" % (old[0], old[-1], len(old)))
    log("[in] index_000300.csv: %s → %s（n=%d）" % (idx[0], idx[-1], len(idx)))
    if not new_dates:
        log("[ok] 已最新（无晚于 %s 的交易日）→ no-op" % old[-1])
        return 0
    log("[diff] 待追加 %d 个交易日: %s" % (len(new_dates), new_dates))

    # ---- 行情覆盖校验：新日期必须真有行情，不能凭空加日历 ----
    syms = sample_syms(U.get("universe") or [])
    if not syms:
        log("!! 抽样标的为空（data_full 不可读？）→ 不推进")
        return 2
    need = int(COVER_MIN * len(syms) + 0.9999)
    dset = set(new_dates)
    cover = {d: 0 for d in new_dates}
    for s in syms:
        for d in date_cover(s, dset):
            cover[d] += 1
    log("[cover] 抽样 %d 只（阈值 %d/%d = %.0f%%）：" % (len(syms), need, len(syms), COVER_MIN * 100))
    bad = []
    for d in new_dates:
        tag = "OK" if cover[d] >= need else "FAIL"
        log("   %s  %d/%d  %s" % (d, cover[d], len(syms), tag))
        if cover[d] < need:
            bad.append(d)
    if bad:
        log("!! 以下日期行情覆盖不足（%s）→ 拒绝推进日历" % bad)
        return 2

    # ---- 单调性自检 + 构造新日历 ----
    new_cal = old + new_dates
    if new_cal[:len(old)] != old or len(new_cal) != len(old) + len(new_dates):
        log("!! 日历前缀被改动（非单调追加）→ 拒绝落盘")
        return 2

    U2 = dict(U)
    U2["calendar"] = new_cal
    U2["cal_maint"] = {
        "date": dt.date.today().isoformat(),
        "ts": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "src": "index_000300.csv",
        "rule": "append trading days later than calendar[-1]（prefix preserved; universe untouched）",
        "appended": new_dates,
        "calendar_n": [len(old), len(new_cal)],
        "cover_check": {"sample": len(syms), "need": need, "cover": cover},
        "why": ("缩量超跌族面板日历此前无日更步骤 → 冻结在生成日，hpdk as_of 永不前进；"
                "本步只追加交易日，不动 universe 成员（保留 universe_maint.py 的僵尸清除结果）"),
    }

    log("\n[check] 新日历前缀 == 旧日历 : %s" % (new_cal[:len(old)] == old))
    log("[check] 长度 %d → %d（+%d）" % (len(old), len(new_cal), len(new_dates)))
    log("[check] 末日 %s == index 末日 %s : %s" % (new_cal[-1], idx[-1], new_cal[-1] == idx[-1]))
    if new_cal[-1] != idx[-1]:
        log("!! 末日不等于 index 末日 → 拒绝落盘")
        return 2
    if not a.apply:
        log("\n[dry-run] 未落盘。加 --apply 生效。")
        return 0

    bak = uni_p.parent / ("universe.json.bak-cal-%s" % STAMP)
    shutil.copy2(uni_p, bak)
    uni_p.write_text(json.dumps(U2, ensure_ascii=False), encoding="utf-8")
    log("\n[apply] 已落盘 %s" % uni_p)
    log("   备份 -> %s" % bak)

    # ---- 落盘后读回自检 ----
    V = json.loads(uni_p.read_text(encoding="utf-8"))
    ok = (V["calendar"][:len(old)] == old and len(V["calendar"]) == len(new_cal)
          and V["calendar"][-1] == idx[-1]
          and [u["sym"] for u in V["universe"]] == [u["sym"] for u in U["universe"]])
    log("[verify] 读回：calendar 前缀保持 / 末日==index 末日 / universe 成员逐位不变 : %s" % ok)
    if not ok:
        log("!! 读回自检失败 → 从备份恢复")
        shutil.copy2(bak, uni_p)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
