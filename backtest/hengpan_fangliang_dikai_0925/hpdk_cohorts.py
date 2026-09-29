# -*- coding: utf-8 -*-
"""hpdk_cohorts.py — 「买日批次跟踪」（2026-09-29，R-hpdk-cohort-0929）

## 为什么需要它
用户 2026-09-28 早盘按面板买入（信号日 09-24 → 买日 09-28），但该批**不在影子跟踪池**内
（影子账本窗口自 SHADOW_START=2026-09-25 起 ⇒ 首个信号日 09-28）⇒ 09-29 到了 T+2 了结日，
用户在面板上**找不到那批、也看不到该挂什么卖价**。这是「指导口径 vs 记账口径」分层的后果。

## 本脚本做什么
以 **买日** 为主键，把每天命中批次（来自 hpdk_hits_history.jsonl）逐笔跟踪到了结：
  · 买入价 = 买日开盘价（冻结口径：09:25 集合竞价撮合价，与「挂 0.99×昨收」等价）
  · 止盈线 = 买入价 × (1+TP)（TP=0.02）
  · 了结日 = 买日之后**第一个交易日**（冻结口径 exit = cal[t+2]）
  · 了结判定（与冻结出场规则逐条一致）：
        了结日 open ≥ 止盈线 → 按 open 成交
        否则 了结日 high ≥ 止盈线 → 按止盈线成交
        否则 → 了结日 close（尾盘）
  · 净收益 = (exit×(1−c) / (entry×(1+c)) − 1)×100，c = 单边成本 0.000346

**不改冻结脚本、不碰 OOS 台账**：只读 data_full 行情 + 本策略自己的命中历史档。
覆盖范围 = hpdk_hits_history.jsonl 里所有买日（**独立于影子账本窗口**）⇒ 用户买过的那批也在内。

用法: python hpdk_cohorts.py            # 写 backtest/hpdk_cohorts.json
"""
import argparse
import datetime as dt
import json
import pathlib
import sys

R = pathlib.Path(__file__).resolve().parents[2]
OUT = R / "backtest" / "hpdk_cohorts.json"
HIST = R / "backtest" / "hpdk_hits_history.jsonl"
IDX = R / "index_000300.csv"
DFULL = R / "data_full"
TP = 0.02                     # 与冻结参数一致（P["TP"]）
COST = 0.000346               # 与冻结参数一致（P["COST_SIDE"]）


def log(*a):
    print(*a, flush=True)


def calendar():
    return [ln.split(",")[0].strip() for ln in
            IDX.read_text(encoding="utf-8-sig").splitlines()[1:] if ln[:4].isdigit()]


_BARS_CACHE = {}      # code-review 修正（0929）：原实现每 (批次 × 标的) 都重读整个 CSV

def bars(sym):
    if sym in _BARS_CACHE:
        return _BARS_CACHE[sym]
    p = DFULL / (sym + ".csv")
    if not p.exists():
        return {}
    out = {}
    try:
        with p.open(encoding="utf-8", errors="replace") as fh:
            head = fh.readline().rstrip("\n").split(",")
            try:
                iD, iO, iH, iC = (head.index("date"), head.index("open"),
                                  head.index("high"), head.index("close"))
            except ValueError:
                return {}
            for ln in fh:
                f = ln.rstrip("\n").split(",")
                if len(f) <= max(iD, iO, iH, iC):
                    continue
                d = f[iD].strip()[:10]
                try:
                    out[d] = (float(f[iO]), float(f[iH]), float(f[iC]))
                except ValueError:
                    continue
    except Exception:
        return {}
    _BARS_CACHE[sym] = out
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hist", default=str(HIST))
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()

    hp = pathlib.Path(a.hist)
    if not hp.exists():
        log("[skip] 未找到命中历史档 %s（先跑 hpdk_candidates.py）" % hp)
        return 0
    hs = [json.loads(l) for l in hp.read_text(encoding="utf-8").splitlines() if l.strip()]
    hs = [x for x in hs if x.get("date")]
    if not hs:
        log("[skip] 命中历史档为空")
        return 0

    cal = calendar()
    cal_last = cal[-1] if cal else None
    batches, n_done, n_hold = [], 0, 0
    for rec in sorted(hs, key=lambda x: x["date"]):
        bd = rec["date"]
        i = cal.index(bd) if bd in cal else None
        ex_d = cal[i + 1] if (i is not None and i + 1 < len(cal)) else None
        # 买日之后第一个交易日若不在日历内（= 尚未发生）→ 待了结
        rows = []
        for c in (rec.get("top") or []):
            sym = ("sh" if str(c).startswith("6") else "sz") + str(c)
            info = next((x for x in (rec.get("rows") or []) if str(x.get("code")) == str(c)), {})
            b = bars(sym)
            e = b.get(bd, (None, None, None))[0] if bd in b else None
            item = dict(code=str(c), sym=sym, name=info.get("name", ""), ind=info.get("ind", ""),
                        gap_pct=info.get("gap_pct"), F=info.get("F"))
            if e is None or e <= 0:
                item.update(entry=None, tp=None, status="缺买日行情")
            else:
                tp = round(e * (1 + TP), 4)
                item.update(entry=round(e, 4), tp=tp)
                if ex_d is None or ex_d not in b:
                    item.update(status="持有中（了结日未到）", exit_date=ex_d, exit=None, ret_pct=None)
                    n_hold += 1
                else:
                    o, h, c2 = b[ex_d]
                    if o >= tp:
                        px, how = o, "了结日开盘≥止盈 → 按开盘成交"
                    elif h >= tp:
                        px, how = tp, "盘中触止盈 → 按止盈价成交"
                    else:
                        px, how = c2, "未达标 → 了结日尾盘"
                    ret = (px * (1 - COST) / (e * (1 + COST)) - 1) * 100
                    item.update(status="已了结", exit_date=ex_d, exit=round(px, 4),
                                exit_how=how, ret_pct=round(ret, 4))
                    n_done += 1
            rows.append(item)
        batches.append(dict(buy_date=bd, signal_date=rec.get("signal_date"),
                            n_pool=rec.get("n_pool"), n_hits=rec.get("n_hits"),
                            exit_date=ex_d, rows=rows))

    out = dict(generated_at=dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
               tp=TP, cost_side=COST, cost_roundtrip_bp=round(COST * 2 * 1e4, 2),
               calendar_last=cal_last,
               rule=("买日批次跟踪：买入价=买日开盘；止盈线=买入价×1.02；了结日=买日之后第一个交易日；"
                     "了结=open≥止盈按open / high≥止盈按止盈 / 否则尾盘close；"
                     "净收益含往返成本 6.92bp。独立于影子账本窗口（覆盖全部命中历史买日）。"),
               n_batches=len(batches), n_settled=n_done, n_holding=n_hold,
               batches=batches)
    pathlib.Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    log("[out] %s  批次 %d（已了结 %d 笔 / 持有中 %d 笔）· 日历末日 %s"
        % (a.out, len(batches), n_done, n_hold, cal_last))
    for bt in batches:
        log("   买日 %s → 了结日 %s · 跟踪 %d 只" % (bt["buy_date"], bt["exit_date"] or "未到", len(bt["rows"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
