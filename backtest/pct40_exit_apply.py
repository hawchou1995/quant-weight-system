# -*- coding: utf-8 -*-
"""pct40 因子化出场 · 生产执行器（先B后A：TRACKS=["track_b"]，轨A 验证后再加入）
语义（与回测一致）：
  每日收盘 → 对模拟盘持仓算 score 截面分位 → 跌出前 40% 记 pending（T 日）
  → 下一交易日(T+1)开盘卖出（含佣金 2.5bp 最低 5 元 + 卖出税 10bp + 滑点 20bp）
  → 得款留现金至下一调仓（不由本器补位；paper 的调仓逻辑照旧）
状态：backtest/pct40_exits_state.json（pending / executed / 对账行）
用法：python backtest/pct40_exit_apply.py   # 每日（在 satellite_paper 之后跑）
"""
import sys, json, time
from pathlib import Path
import numpy as np, pandas as pd

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
HERE = BASE / "backtest"
PAPER = HERE / "satellite_paper.json"
STATE = HERE / "pct40_exits_state.json"
sys.path.insert(0, str(HERE))
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)

TRACKS = ["track_b", "track_a"]   # 2026-09-15 拍板：轨A pct40 同步投产（先B后A 已验证）
COMM, TAX, SLIP, MIN_COMM = 0.00025, 0.0010, 0.0020, 5.0   # 与 satellite_paper meta 口径一致
PCT_CUT = 0.40

def px_of(code):
    for c in (code, "sh" + code, "sz" + code, "bj" + code):
        f = BASE / "data_full" / f"{c}.csv"
        if f.exists():
            d = pd.read_csv(f, dtype={"date": str}).sort_values("date")
            return {r.date: (float(r.open), float(r.close)) for r in d.itertuples()}
    return {}

def pct_map(track):
    """当日 score 截面分位（返回 {code: pct}，均为"越高越该卖"语义）"""
    if track == "track_b":
        sys.path.insert(0, str(HERE / "oss_0913"))
        import oss_super_prod_0913 as S
        di = S.ND - 1
        sc = S.COMP_SUPER[di]
        series = pd.Series(np.where(np.isfinite(sc) & S.ELIG_SUPER[di], sc, np.nan),
                           index=[str(c) for c in S.codes]).dropna()
        return (-series).rank(pct=True).to_dict(), str(S.cal[-1])       # 高分好 → 降序分位，>0.40 触发
    else:                                                              # track_a（待启用）
        src = open(HERE / "signal_satellite_0913.py", encoding="utf-8").read().split("def main()")[0]
        src = src.replace("BASE = Path(__file__).resolve().parents[1]", f'BASE = Path(r"{BASE}")')
        G = {"__file__": str(HERE / "signal_satellite_0913.py")}
        exec(src, G)
        top, df, _gate = G["signal_turn_gate"]({})   # 与轨A 生产信号同源（三低 rank 和）
        s = df.set_index("code")["rk"].rank(pct=True)
        return s.to_dict(), str(G.get("LAST_DAY"))                     # 低分好 → 升序分位，>0.40 触发

def main():
    paper = json.loads(PAPER.read_text(encoding="utf-8"))
    st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else dict(
        created=str(pd.Timestamp.today().date()), tracks=list(TRACKS), pending={}, executed=[], nav=[])
    for tk in TRACKS: st["pending"].setdefault(tk, [])
    touched = False
    for tk in TRACKS:
        pos = (paper.get("positions") or {}).get(tk) or {}
        cash_key = {"track_a": "cash_a", "track_b": "cash_b"}[tk]
        cash = float((paper.get("meta") or {}).get(cash_key, 0.0))
        # ---- 1) 执行 pending（T+1 开盘卖）----
        keep = []
        for item in st["pending"][tk]:
            code = item["code"]
            if code not in pos:
                log(f"  {tk} {code} 已不在持仓（调仓卖出）→ 撤销 pending")
                continue
            pxd = px_of(code)
            dates = sorted(pxd.keys())
            nxt = [d for d in dates if d > item["trigger_date"]]
            if not nxt:
                keep.append(item); continue                                # 次交易日数据未到 → 等
            ex_date = nxt[0]
            if len(dates) < 2 or dates[-1] < ex_date:
                keep.append(item); continue
            op = pxd[ex_date][0]; sh = float(pos[code].get("shares") or 0)
            if sh <= 0 or not np.isfinite(op) or op <= 0:
                keep.append(item); continue
            px = op * (1 - SLIP); amt = px * sh
            fee = max(amt * COMM, MIN_COMM) + amt * TAX
            cash += amt - fee
            paper["fills"].append(dict(date=ex_date, track=tk, code=code, name=pos[code].get("name"),
                                       px=round(px, 3), shares=sh, amount=round(amt - fee, 2),
                                       side="sell", reason="pct40", pct=round(item.get("pct", float("nan")), 4)))
            log(f"  {tk} 出场 {code} @ {px:.2f}（trigger {item['trigger_date']} → 执行 {ex_date}，pct={item.get('pct'):.3f}）")
            st["executed"].append(dict(track=tk, code=code, trigger_date=item["trigger_date"], exec_date=ex_date,
                                       px=round(px, 3), shares=sh, pct=item.get("pct")))
            pos.pop(code, None)
            touched = True
        st["pending"][tk] = keep
        # ---- 2) 今日判定 ----
        if not pos:
            log(f"{tk}: 无持仓（待建仓）——跳过判定")
            continue
        pmap, asof = pct_map(tk)
        n_flag = 0
        for code in list(pos.keys()):
            v = pmap.get(code)
            if v is None: continue
            pos[code]["pct40"] = round(float(v), 4)
            if v > PCT_CUT and code not in [x["code"] for x in st["pending"][tk]]:
                st["pending"][tk].append(dict(code=code, trigger_date=asof, pct=float(v)))
                n_flag += 1
                log(f"  {tk} 触发 {code} pct={v:.3f}（跌出前40%）→ 明日开盘卖出")
        # ---- 3) 对账行 ----
        mv = 0.0
        for code, p in pos.items():
            pxd = px_of(code)
            if pxd:
                last = sorted(pxd.keys())[-1]
                mv += float(p.get("shares") or 0) * pxd[last][1]
        nav = cash + mv
        st["nav"].append(dict(date=asof, track=tk, nav=round(nav, 2), cash=round(cash, 2),
                              n_held=len(pos), n_flag_today=n_flag, n_pend=len(st["pending"][tk])))
        log(f"{tk}: 持仓 {len(pos)} | 今日触发 {n_flag} | pending {len(st['pending'][tk])} | 净值 {nav:.2f}（现金 {cash:.2f} + 市值 {mv:.2f}）")
        if touched:
            paper["meta"][cash_key] = round(cash, 2)
    if touched:
        paper["positions"] = paper.get("positions") or {}
        PAPER.write_text(json.dumps(paper, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
        log("paper 已更新（出场回填）")
    st["executed"] = st["executed"][-200:]; st["nav"] = st["nav"][-600:]
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    log(f"state -> {STATE.name} | executed {len(st['executed'])} | pending {sum(len(v) for v in st['pending'].values())}")

if __name__ == "__main__":
    main()
