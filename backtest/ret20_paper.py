# -*- coding: utf-8 -*-
"""ret20 倾斜臂模拟盘（#2 λ0.2 / #4 λ0.3 · R-ret20-paper-0917）
=========================================================================
拍板（2026-09-17 用户）：#2 ret20 λ0.2 / #4 ret20 λ0.3 **投产并加模拟盘**。
出厂争议已裁决（用户 09-17 拍板表）：
    #2 ret20 λ0.2 = 影子轨主候选（继续纸面跟踪，10 月中首检）
    #4 ret20 λ0.3 = 影子轨陪跑
故本脚本**不改生产 composite**（冻结引擎 oss_0913 原样）：
    生产 composite = BASE（13 因子 ICIR 复合）；λ 臂以**独立模拟盘账户**落地，
    与轨B 同额（各 68,000）以便逐日 A/B —— 纯对照，**不构成任何实盘资金申领**。
    毕业判据触发后才由用户拍板是否给配额（见 meta.graduation）。

臂定义（与 backtest/shadow_ret20.py 同源，禁两处各写一份）：
    base = zclip(composite())
    l02  = (zclip(comp) + 0.2·zclip(ret20)) / 1.2
    l03  = (zclip(comp) + 0.3·zclip(ret20)) / 1.3
    ret20 = close_ff / shift(20) − 1；zclip：ELIG3 掩码 + 截面 z 后截 ±3

口径（与 backtest/satellite_paper_0914.py 完全一致，禁改）：
    成本 = 佣金 2.5bp(最低5元) + 印花税 10bp(卖出) + 滑点 20bp/边
    T 日收盘定信号 → T+1 开盘成交（open×(1+SLIP)）；整百股；等权分配
    调仓周期 = 轨B 同源（REBAL_DAYS = 30）；调仓日按当日臂清单重建
标记：每日末收盘 mark 净值，追加 nav_history（同日不重复覆盖）

账本：backtest/ret20_paper_l02.json / ret20_paper_l03.json（与轨B 同 schema）
信号：backtest/shadow_ret20/state.json 的 lists（每日影子轨产出，唯一来源）

用法：
    python backtest/ret20_paper.py                      # 日更：必要时建仓 + mark
    python backtest/ret20_paper.py --init-fill [DATE]   # 指定成交日建仓（默认信号日 T+1）
    python backtest/ret20_paper.py --dry                # 预览，不写盘
"""
import json
import math
import sys
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent.parent  # 2026-09-24 云端可移植（原写死 D:/…，本机解析恒等）
HERE = BASE / "backtest"
SHADOW_STATE = HERE / "shadow_ret20" / "state.json"
CAL = BASE / "index_000300.csv"
COMM, TAX, SLIP, MIN_COMM, LOT = 0.00025, 0.0010, 0.0020, 5.0, 100
REBAL_DAYS = 30                       # 与轨B 同源（satellite_pool.track_b.rebal）

sys.path.insert(0, str(HERE))
import satellite_cfg as CFG                                  # 配额单一来源（R-single-track-0915）

BASIS = float(CFG.CAP_B)              # 各臂名义 = 轨B 同额（68,000）→ 逐日 A/B 可比、零资金申领
ARMS = ["l02", "l03"]
ARM_LABEL = {"l02": "ret20 倾斜 λ0.2（#2 · 影子轨主候选）", "l03": "ret20 倾斜 λ0.3（#4 · 影子轨陪跑）"}
STATE_MAP = {a: HERE / f"ret20_paper_{a}.json" for a in ARMS}

GRADUATION = {
    "first_check": "2026-10-15",
    "criteria": ["① 影子 NAV ≥ BASE 臂（同窗）",
                 "② 月度收益多数为正（≥60% 月份）",
                 "③ 相对回撤 ≤ BASE 臂 + 5pp"],
    "on_pass": "通过后由用户拍板是否给实盘配额；本脚本不得自行改生产 composite",
    "on_fail": "归档该臂（写明证伪依据），不保留半成品",
}
HARD_FLAGS = [
    "① 研究读数（v0916 off0）：λ0.2 +25.08%/S1.411/回撤−24.6%/50bp 19.25；λ0.3 +24.36%/S1.376/回撤−24.8%/50bp 18.67",
    "② 生产 BASE 锚 = engine_anchor.base_off0_ann（每日由 shadow_ret20 重写；漂移 >3pp 研究侧中止）",
    "③ 安慰剂 p：λ0.2=0.05 / λ0.3=0.05（仅 1 次入样，样本外记录 = 0 天）→ 这才是要模拟盘跑起来的原因",
    "④ 与轨B 的 Top20 重合度（0917）：λ0.2 0.818 / λ0.3 0.739 → 高重合，本质是同一篮子的偏斜",
]


def load_px(code):
    """{date: (open, close)}；code 形如 600668（自动补 sh/sz/bj 前缀）"""
    f = BASE / "data_full" / f"{code}.csv"
    if not f.exists():
        for pre in ("sh", "sz", "bj"):
            g = BASE / "data_full" / f"{pre}{code}.csv"
            if g.exists():
                f = g
                break
    if not f.exists():
        return {}
    df = pd.read_csv(f, dtype={"date": str}).sort_values("date")
    return {r.date: (float(r.open), float(r.close)) for r in df.itertuples()}


def calendar():
    idx = pd.read_csv(CAL, parse_dates=["date"])
    return sorted(idx["date"].dt.strftime("%Y-%m-%d").tolist())


def read_shadow():
    if not SHADOW_STATE.exists():
        return {}
    try:
        return json.loads(SHADOW_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def lists_for_date(date_str):
    """从 shadow_ret20/daily_metrics.jsonl 取指定日期的臂清单（逐日一行，含 lists）。"""
    m = HERE / "shadow_ret20" / "daily_metrics.jsonl"
    if not m.exists() or not date_str:
        return {}
    try:
        for ln in reversed(m.read_text(encoding="utf-8").strip().splitlines()):
            try:
                row = json.loads(ln)
            except Exception:
                continue
            if row.get("date") == date_str:
                return row.get("lists") or {}
    except Exception:
        pass
    return {}


def load_state(arm):
    p = STATE_MAP[arm]
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def new_state(arm, last, sig):
    return dict(
        meta=dict(strategy=ARM_LABEL[arm], created=last, signal_date=sig, arm=arm,
                  basis=BASIS, scope="卫星层 · 与轨B 同额纯对照（零实盘资金申领）",
                  cost_model="佣金 2.5bp(最低5元) + 印花税 10bp(卖出) + 滑点 20bp/边",
                  cadence=f"建仓 T+1 开盘；调仓 {REBAL_DAYS} 日（轨B 同源）",
                  lists_source="backtest/shadow_ret20/state.json（影子轨唯一来源）",
                  baseline="生产 composite = BASE，未改（R-ret20-paper-0917）",
                  graduation=GRADUATION, hard_flags=HARD_FLAGS),
        track=arm, cash=BASIS, positions={}, fills=[], events=[], nav_history=[])


def build(arm, st, codes, fill_date, budget):
    """等权建仓/调仓：先卖后买（同日按开盘价×SLIP）"""
    ev, trades = [], []
    pos = st["positions"]
    pxd = {c: load_px(c) for c in set(list(pos) + list(codes))}

    def px_of(c, d):
        v = pxd.get(c) or {}
        if d not in v:
            return None
        return v[d][0] * (1 + SLIP)

    cash = float(st["cash"])
    # 卖
    for c in list(pos):
        p = px_of(c, fill_date)
        if p is None:
            continue
        sh = float(pos[c]["shares"])
        amt = p * sh
        fee = max(amt * COMM, MIN_COMM) + amt * TAX
        cash += amt - fee
        trades.append(dict(date=fill_date, code=c, name=pos[c].get("name", c), side="sell",
                           px=round(p, 3), shares=int(sh), amount=round(amt - fee, 2)))
        ev.append(f"卖出 {c} {int(sh)} 股 @ {p:.3f}（净 {amt - fee:.2f}）")
        del pos[c]
    # 买
    if codes:
        per = cash / len(codes)
        for c in codes:
            p = px_of(c, fill_date)
            if p is None:
                ev.append(f"跳过 {c}：{fill_date} 无行情")
                continue
            lots = math.floor(min(per, cash) / (p * LOT))
            sh = lots * LOT
            if lots < 1:
                ev.append(f"跳过 {c}：资金不足一手（预算 {per:.0f} < {p * LOT:.0f}）")
                continue
            amt = p * sh
            fee = max(amt * COMM, MIN_COMM)
            while lots > 0 and amt + fee > cash:
                lots -= 1
                sh = lots * LOT
                amt = p * sh
                fee = max(amt * COMM, MIN_COMM)
            if lots < 1:
                continue
            cash -= amt + fee
            pos[c] = dict(shares=float(sh), cost=(amt + fee) / sh, name=c, last=pxd[c][fill_date][1])
            trades.append(dict(date=fill_date, code=c, name=c, side="buy",
                               px=round(p, 3), shares=int(sh), amount=round(amt + fee, 2)))
            ev.append(f"买入 {c} {int(sh)} 股 @ {p:.3f}（含费 {amt + fee:.2f}）")
    st["cash"] = round(cash, 2)
    st["fills"].extend(trades)
    st["events"].extend(dict(date=fill_date, event=e) for e in ev)
    st["events"] = st["events"][-60:]
    return len(trades)


def main():
    dry = "--dry" in sys.argv
    target = None
    if "--init-fill" in sys.argv and len(sys.argv) > sys.argv.index("--init-fill") + 1:
        target = sys.argv[sys.argv.index("--init-fill") + 1]

    cal = calendar()
    if not cal:
        print("!! 日历为空（index_000300.csv 不可读）——中止")
        return 1
    last = cal[-1]
    sh = read_shadow()
    lists = (sh.get("lists") or {})
    sig = sh.get("last_signal_date") or sh.get("start_date")
    # 影子轨把当日清单写在 daily_metrics 末行；无则退回逐臂读 metrics
    if not lists:
        m = HERE / "shadow_ret20" / "daily_metrics.jsonl"
        if m.exists():
            try:
                row = json.loads(m.read_text(encoding="utf-8").strip().splitlines()[-1])
                lists, sig = row.get("lists", {}), row.get("date")
            except Exception:
                pass

    upd = []
    for arm in ARMS:
        codes = [c for c in (lists.get(arm) or []) if c]
        st = load_state(arm)
        if st is None:
            if not codes:
                upd.append((arm, f"影子轨无 {arm} 清单 → 未建档"))
                continue
            st = new_state(arm, last, sig)
            st["events"].append(dict(date=last, event=f"建档：名义 {BASIS:.0f}（与轨B 同额纯对照），"
                                                      f"信号日 {sig}，等 T+1 开盘建仓 {len(codes)} 只"))
        pos = st["positions"]
        basis = float(st["meta"].get("basis", BASIS))

        # ---- 成交日 ----
        # ⚠ 2026-09-18 修（R-ret20-fix-0918）：**首建仓必须用账户自己存的 meta.signal_date**，
        #    不能用每轮重算的 shadow 最新信号日 —— 否则 09-17 信号的 T+1（09-18）会被永久跳过
        #    （09-18 当天 shadow 把 last_signal_date 覆写成 09-18，auto 只认 > 09-18 的 09-21）。
        sig_eff = sig
        if not pos and (st.get("meta") or {}).get("signal_date"):
            sig_eff = st["meta"]["signal_date"]
            hist = lists_for_date(sig_eff)
            if hist.get(arm):
                codes = [c for c in hist[arm] if c]
                if sig_eff != sig:
                    print(f"[{arm}] 首建仓：改用账户信号日 {sig_eff}（shadow 最新 {sig}）→ {len(codes)} 只")
        last_fill = (st["fills"][-1]["date"] if st["fills"] else None)
        auto = [d for d in cal if sig_eff and d > sig_eff]
        fill_date = target or (auto[0] if auto else None)
        need_init = (not pos) and float(st["cash"]) > 0
        # 调仓：距上次成交 ≥ REBAL_DAYS 个交易日，且清单与在仓集合不同
        rebal = False
        if pos and last_fill and not target:
            try:
                gap = sum(1 for d in cal if last_fill < d <= last)
            except Exception:
                gap = 0
            rebal = (gap >= REBAL_DAYS) and (set(codes) != set(pos))
        do = need_init or rebal
        n = 0
        if do and fill_date and codes:
            n = build(arm, st, codes, fill_date, float(st["cash"]))
            if n:
                print(f"[{arm}] {'建仓' if need_init else '调仓'} @ {fill_date}：{n} 笔 → 在仓 {len(st['positions'])} 只")
                st["meta"]["signal_date"] = fill_date
                st["meta"]["filled"] = fill_date
            else:
                print(f"[{arm}] {fill_date} 无可成交（行情未到）")
        elif need_init and not fill_date:
            print(f"[{arm}] 待建仓但 T+1 数据未到（信号 {sig}，日历末 {last}）")

        # ---- mark ----
        pxc, mv = {}, 0.0
        for c, p in st["positions"].items():
            if c not in pxc:
                pxc[c] = load_px(c)
            v = pxc[c]
            if last in v:
                p["last"] = v[last][1]
            mv += float(p["shares"]) * float(p.get("last", 0.0))
        cash = float(st["cash"])
        nav = cash + mv
        ret = nav / basis - 1
        if st["positions"]:
            nh = st["nav_history"]
            row = dict(date=last, nav=round(nav, 2), pos=round(mv, 2), cash=round(cash, 2),
                       ret=round(ret, 5))
            if nh and nh[-1].get("date") == last:
                nh[-1].update(row)
            else:
                nh.append(row)
        if not dry:
            STATE_MAP[arm].write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
        upd.append((arm, f"在仓 {len(st['positions'])} 只 | 现金 {cash:.2f} + 市值 {mv:.2f} "
                         f"= 净值 {nav:.2f}（{ret:+.2%}）"))

    print(f"ret20 倾斜臂模拟盘 | 信号日 {sig} | 日历末 {last} | 名义各 {BASIS:.0f}（与轨B 同额纯对照）")
    for arm, msg in upd:
        print(f"  [{arm}] {msg}")
    print(f"  毕业首检 {GRADUATION['first_check']}：{' / '.join(GRADUATION['criteria'])}")
    if dry:
        print("[dry] 未写盘。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
