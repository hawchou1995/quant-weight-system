# -*- coding: utf-8 -*-
"""双卫星模拟盘账本更新器（轨A 冷门低波 Top10 / 轨B SUPER Top20）
=================================================================
台账：backtest/satellite_paper.json（meta/fills/positions/nav_history/events）
口径（建档 meta）：初始 68000 = 轨A 34000 + 轨B 34000
    成本 = 佣金 2.5bp(最低5元) + 印花税 10bp(卖出) + 滑点 20bp/边
行为：
  --init-fill [YYYY-MM-DD]  空仓轨按 satellite_pool.json 目标清单在该日开盘建仓（默认池 asof 的下一交易日）
  默认                       每轨按最新收盘 mark 净值，追加 nav_history（同日不重复追加）
注意：池文件 rows[].lot 实为 close×100 展示值（已实测），本脚本自算手数（金额等分，整百股）
用法：python backtest/satellite_paper_0914.py --init-fill
      python backtest/satellite_paper_0914.py            # 日更 mark
"""
import json, math, sys
from pathlib import Path
import pandas as pd

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
STATE = BASE / "backtest" / "satellite_paper.json"          # 旧单文件（仅迁移兼容）
STATE_A = BASE / "backtest" / "satellite_paper_a.json"      # 轨A 独立账户（对照轨）
STATE_B = BASE / "backtest" / "satellite_paper_b.json"      # 轨B 独立账户（主轨）
POOL = BASE / "backtest" / "satellite_pool.json"
INIT_SNAP = BASE / "backtest" / "satellite_paper_init.json"   # 建仓目标快照(冻结信号日清单，防池重建改写)
COMM, TAX, SLIP, MIN_COMM = 0.00025, 0.0010, 0.0020, 5.0
TRACKS = ["track_a", "track_b"]
CASH_KEY = {"track_a": "cash_a", "track_b": "cash_b"}
STATE_MAP = {"track_a": STATE_A, "track_b": STATE_B}
sys.path.insert(0, str(Path(__file__).parent))
try:
    import satellite_cfg as CFG
    BASIS = {"track_a": CFG.NAV_A, "track_b": CFG.CAP_B}     # 各轨名义基数（净值口径）
except Exception:
    BASIS = {"track_a": 34000.0, "track_b": 34000.0}


def load_state():
    """从两个独立账户文件合并为内部单字典；两文件缺失则回退读旧单文件（迁移兼容）。"""
    if not (STATE_A.exists() and STATE_B.exists()):
        return json.loads(STATE.read_text(encoding="utf-8"))
    st = {"meta": {}, "fills": [], "positions": {}, "nav_history": [], "events": []}
    by_date = {}
    for tk, f in STATE_MAP.items():
        d = json.loads(f.read_text(encoding="utf-8"))
        for k, v in (d.get("meta") or {}).items():
            st["meta"].setdefault(k, v)
        st[CASH_KEY[tk]] = d.get("cash")
        st["positions"][tk] = d.get("positions", {})
        st["fills"] += d.get("fills", [])
        st["events"] += d.get("events", [])
        for h in d.get("nav_history", []):
            by_date.setdefault(h["date"], {"date": h["date"]}).update(
                {k: v for k, v in h.items() if k != "date"})
    st["nav_history"] = [by_date[k] for k in sorted(by_date)]
    st["meta"]["initial_cash"] = sum(BASIS.values())
    return st


def save_state(st):
    """把内部单字典按轨拆成两个独立账户文件（各含自己的 cash/positions/fills/nav）。"""
    for tk, f in STATE_MAP.items():
        meta = {k: v for k, v in (st.get("meta") or {}).items() if not k.startswith("cash_")}
        meta.update(dict(track=tk, basis=BASIS[tk],
                         role=("对照轨·零实盘资金" if tk == "track_a" else "主轨")))
        d = dict(meta=meta, track=tk, cash=st.get(CASH_KEY[tk]),
                 positions=st.get("positions", {}).get(tk, {}),
                 fills=[x for x in st.get("fills", []) if x.get("track") == tk],
                 events=[x for x in st.get("events", []) if x.get("track", tk) == tk],
                 nav_history=[{"date": h["date"], **{k: v for k, v in h.items()
                                                     if k in (tk, f"{tk}_pos")}}
                              for h in st.get("nav_history", []) if tk in h])
        f.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")

def load_px(code, date=None):
    """返回 {date: (open, close)}；date=None 全量"""
    f = BASE / "data_full" / f"{code}.csv"
    if not f.exists():
        for pre in ("sh", "sz", "bj"):
            g = BASE / "data_full" / f"{pre}{code}.csv"
            if g.exists(): f = g; break
    if not f.exists(): return {}
    df = pd.read_csv(f, dtype={"date": str}).sort_values("date")
    if date is not None:
        r = df[df["date"] == date]
        return {} if r.empty else {date: (float(r["open"].iloc[0]), float(r["close"].iloc[0]))}
    return {r.date: (float(r.open), float(r.close)) for r in df.itertuples()}

def main():
    st = load_state()
    pool = json.loads(POOL.read_text(encoding="utf-8"))
    dry = "--dry" in sys.argv
    target_date = None
    if "--init-fill" in sys.argv and len(sys.argv) > sys.argv.index("--init-fill") + 1:
        target_date = sys.argv[sys.argv.index("--init-fill") + 1]

    # --snapshot-init: 冻结当前池为建仓目标快照（建档日执行一次），并记录事件
    if "--snapshot-init" in sys.argv:
        snap = dict(asof=pool.get("asof"), frozen_at=pd.Timestamp.today().strftime("%Y-%m-%d"),
                    tracks={tk: dict(name=(pool.get(tk) or {}).get("name"), rows=(pool.get(tk) or {}).get("rows", []))
                            for tk in TRACKS})
        if dry:
            print("[dry] would write", INIT_SNAP.name, "tracks:", {k: len(v["rows"]) for k, v in snap["tracks"].items()})
            return
        INIT_SNAP.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"已冻结建仓快照 asof={snap['asof']} → {INIT_SNAP.name}（A {len(snap['tracks']['track_a']['rows'])} / B {len(snap['tracks']['track_b']['rows'])}）")

    # 建仓目标 = 冻结快照（优先，防池重建改写）→ 否则当前池
    init_src = pool
    if INIT_SNAP.exists():
        s = json.loads(INIT_SNAP.read_text(encoding="utf-8"))
        init_src = dict(asof=s.get("asof"), **{tk: (s["tracks"].get(tk) or {}) for tk in TRACKS})
        print(f"建仓快照: asof={init_src.get('asof')}（frozen）")

    # 最新交易日（以池内第一只为样本）
    sample = next(r["code"] for r in (pool["track_a"]["rows"] or [{"code": "sh600519"}]))
    cal = sorted(load_px(sample).keys())
    last = cal[-1]
    print(f"数据截至 {last} | 池 asof {pool.get('asof')}")

    # 自动建仓：空仓轨 + 目标清单 → 信号日(asof)之后的第一个交易日开盘执行
    asof = init_src.get("asof")
    auto_dates = [d for d in cal if asof and d > asof]
    fill_date = target_date or (auto_dates[0] if auto_dates else None)
    need_fill = {tk: (not st["positions"].get(tk or "")) and bool((init_src.get(tk) or {}).get("rows")) for tk in TRACKS}
    if fill_date and any(need_fill.values()):
        print(f"== init-fill @ {fill_date} 开盘（{'+'.join(k for k,v in need_fill.items() if v)}）==")
    else:
        if any(need_fill.values()):
            print(f"!! 待建仓但数据未到（信号日 {asof}，最新数据 {last}）——等收盘数据后自动执行")
        fill_date = None

    total_nav, total_cash, total_pos = 0.0, 0.0, 0.0
    for tk in TRACKS:
        tk_pool = init_src.get(tk) or {}
        rows = tk_pool.get("rows", [])
        # ⚠ 现金取值优先级：顶层 cash_x = 实盘剩余现金（权威）；meta.cash_x = 初始分配额（仅在首次建仓时兜底）。
        #    2026-09-14 事故：原写法 `st["meta"] if CASH_KEY in st["meta"]` 让已花掉的 34000 被当成剩余现金
        #    → NAV 被写成 +75.59%（实际 +0.185%）。已修正，勿回退。
        cash = float(st[CASH_KEY[tk]] if CASH_KEY[tk] in st else st["meta"][CASH_KEY[tk]])
        pos = st["positions"].setdefault(tk, {})

        # ---- 建仓 ----
        if fill_date and not pos and rows:
            per_amount = cash / len(rows)
            buys = []
            for r in rows:
                code = r["code"]
                pxd = load_px(code, fill_date)
                if not pxd:
                    print(f"  !! {tk} {code} {r.get('name')} 无 {fill_date} 数据，跳过")
                    continue
                o = pxd[fill_date][0]
                px = o * (1 + SLIP)
                lots = math.floor(min(per_amount, cash) / (px * 100.0))
                if lots < 1:
                    print(f"  !! {tk} {code} 资金不足一手，跳过")
                    continue
                sh = lots * 100.0
                amt = px * sh
                fee = max(amt * COMM, MIN_COMM)
                if amt + fee > cash:
                    lots -= 1; sh = lots * 100.0; amt = px * sh; fee = max(amt * COMM, MIN_COMM)
                cash -= amt + fee
                pos[code] = dict(shares=sh, cost=(amt + fee) / sh, name=r.get("name"), industry=r.get("industry"))
                buys.append((code, r.get("name"), round(px, 3), int(sh), round(amt + fee, 2)))
            st[CASH_KEY[tk]] = round(cash, 2)
            for b in buys:
                st["fills"].append(dict(date=fill_date, track=tk, code=b[0], name=b[1], px=b[2], shares=b[3], amount=b[4], side="buy"))
            st["events"].append(dict(date=fill_date, event=f"{tk} 建仓 {len(buys)}/{len(rows)} 只，金额/只≈{per_amount:.0f}，滑点 20bp+佣金2.5bp"))
            print(f"  {tk}: 买入 {len(buys)} 只，剩现金 {cash:.2f}")

        # ---- mark 净值 ----
        mv = 0.0
        for code, p in pos.items():
            pxc = load_px(code)
            if last in pxc:
                p["last"] = pxc[last][1]
                mv += p["shares"] * pxc[last][1]
            elif "last" in p:
                mv += p["shares"] * p["last"]
        nav = cash + mv
        total_nav += nav; total_cash += cash; total_pos += mv
        has_activity = bool(pos) or any(f.get("track") == tk for f in st["fills"])
        if not has_activity:
            print(f"  {tk}: 未建仓（待信号后首个交易日开盘执行），跳过净值记录")
            continue
        nh = st["nav_history"]
        label = f"{tk}"
        if nh and nh[-1].get("date") == last and label in nh[-1]:
            nh[-1][label] = round(nav, 2)
            nh[-1][f"{label}_pos"] = round(mv, 2)
        else:
            nh.append({**({} if not nh or nh[-1].get("date") != last else nh[-1]), "date": last, label: round(nav, 2), f"{label}_pos": round(mv, 2)})
        print(f"  {tk}: 现金 {cash:.2f} + 市值 {mv:.2f} = 净值 {nav:.2f}（{nav/BASIS[tk]-1:+.2%}）")

    # total 汇总到最新 nav 行
    nh = st["nav_history"]
    if nh:
        nh[-1]["total"] = round(total_nav, 2)
        nh[-1]["total_ret"] = round(total_nav / st["meta"]["initial_cash"] - 1, 5)
    st["events"] = st["events"][-40:]
    if dry:
        tail = json.dumps(nh[-1], ensure_ascii=False) if nh else "（空 nav_history：两轨均未建仓）"
        print("[dry] 未写盘。将写 nav_history 尾行：", tail)
        return
    save_state(st)
    print(f"== 合计净值 {total_nav:.2f} / {st['meta']['initial_cash']} = {total_nav/st['meta']['initial_cash']-1:+.2%} → {STATE.name}")

if __name__ == "__main__":
    main()
