# -*- coding: utf-8 -*-
"""bt_crosscheck.py —— 用第三方引擎 backtrader 独立重跑「横盘低开·两日」的**组合记账层**（2026-09-28）

定位
----
本脚本属于**第三方复核**，不是策略实现的一部分：
  · 只读**冻结逐笔**（_v_g00_trades.jsonl）与**面板**（panel_oos.npz）；
  · **不 import** 本项目任何自研记账实现（x2_sens / sim_portfolio / x6_t0_audit 一律不引用）；
  · 现金记账、订单生命周期、成交时点、逐日盯市交给 backtrader 的 Cerebro / Broker 完成。

所用 backtrader 技能要点（安装自 lzwme/finance-quant-skills 的 backtrader 技能）：
  · Cerebro（引擎）/ Strategy（策略）/ Data Feed（PandasData，逐标的 1 个）
  · cheat_on_open=True ⇒ `next_open()` 里的市价单在**当根开盘**成交
  · bt.Order.Close  ⇒ 在**下一根收盘**成交（源码：cerebro._brokernotify → broker.next() 用 close[0]）
  · Broker.setcommission(commtype=COMM_PERC, stocklike=True, percabs=True) ⇒ 成交额×费率
  · Analyzer：SharpeRatio / DrawDown / TimeReturn

bar 内执行顺序（读 backtrader 源码确认，cerebro.py `_runnext`）：
  数据推进 → next_open() → _brokernotify(){ broker.next() 执行订单 → 交付通知 } → next()
  ⇒ 同一根里【上一根排队的出场单】先于【本根 next_open 下的入场单】执行（按创建顺序 FIFO）。

两种日序（用于独立确认勘误 E-15 的方向）
  · entry_first（正确）：出场单是 Close 型 ⇒ 在**当根收盘**成交；且入场额度只用**结算前现金**
    （即 09:25 只能花开盘前已有的钱，不能用当天 15:00 才回笼的钱）
  · exit_first （缺陷）：出场单是 Market 型 ⇒ 在**当根开盘**成交，回笼资金先于同根买入可用
    ⇒ 同一笔资本在一天里被用两次（复现 E-15 之前的旧序）

用法:
  python bt_crosscheck.py --cache DIR --kslot 20 --order entry_first --out FILE [--start D --end D]
"""
import argparse, json, math, os, pathlib, sys, time
import numpy as np
import pandas as pd
import backtrader as bt

COST = 0.000346
K = 10
SAFETY = 1e-6            # 额度相对安全系数：覆盖面板 float32 盯市带来的 ~1e-7 现金噪声（见报告 §4）
ANN = 244.0

# 外部参照读数（自研权威口径，勘误 E-15 修正后；本脚本只作为对照目标，不引用其代码）
REFERENCE = {
    20: dict(ann=47.17, mdd=-26.81, sharpe=2.19, n_entries=23002, deploy_pct=40.43),
    4:  dict(ann=76.61, mdd=-33.63, sharpe=2.29, n_entries=4886,  deploy_pct=42.82),
}
REFERENCE_EXIT_FIRST = {20: dict(ann=47.77, mdd=-29.13), 4: dict(ann=189.75, mdd=-51.18)}


def log(*a):
    print(*a, flush=True)


def _jdef(o):
    """JSON 序列化兜底：numpy 标量 → Python 标量。"""
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)

def snap_lo(cal, d):
    for i, x in enumerate(cal):
        if x >= d:
            return i
    return len(cal) - 1


def snap_hi(cal, d):
    for i in range(len(cal) - 1, -1, -1):
        if cal[i] <= d:
            return i
    return 0


def fill_invalid(a):
    """非法值（NaN/≤0）前向＋回填 —— 只为让数据馈合法。
    按构造（报告 §4），被填补的位置不会参与任何盯市或成交。"""
    a = np.asarray(a, dtype="float64").copy()
    bad = ~np.isfinite(a) | (a <= 0)
    n = int(bad.sum())
    if bad.all():
        return np.ones_like(a), n
    idx = np.where(~bad, np.arange(len(a)), 0)
    np.maximum.accumulate(idx, out=idx)
    a = a[idx]
    bad2 = ~np.isfinite(a) | (a <= 0)
    if bad2.any():
        a[bad2] = a[~bad2][0]
    return a, n


class Ledger(bt.Strategy):
    params = dict(kslot=20, order="entry_first", cost=COST, k=K,
                  by_day=None, exit_on=None, sym2idx=None, cal=None, panelC=None, jof=None)

    def __init__(self):
        self.by_day = self.p.by_day
        self.exit_on = self.p.exit_on
        self.sym2idx = self.p.sym2idx
        self._cal = self.p.cal
        self._panelC = self.p.panelC
        self._jof = self.p.jof
        self.pos = {}            # 买入单 ref -> dict(sym,size,entry_open,exit_date,exit_px)
        self.issued = {}         # 出场日 -> [(sym,size,exit_px,pos_ref)]
        self.nav = {}
        self.depl = {}
        self.n_entries = 0
        self.entries_list = []
        self.sell_issue = {}
        self.sell_log = []
        self.n_margin = 0
        self.n_rejected = 0
        self.n_nudge = 0
        self.n_dedupe = 0
        self.n_kslot_break = 0
        self.n_alloc_break = 0
        self.n_cash_audit = 0
        self.max_cash_gap = 0.0
        self.sym_ref = {}
        self.margin_log = []
        self.audit_log = []
        self.audit_bad = []
        self.issue_log = {}
        self.n_buy_fills = 0
        self.n_sell_fills = 0
        self.n_sell_unmatched = 0
        self.n_sell_pending_at_end = 0
        self._cash_expect = None
        self._nav_prev = None
        self._mirror = None

    # --- 无指标 ⇒ 全 bar 同一实现 ---
    def prenext_open(self):   self._open_step()
    def nextstart_open(self): self._open_step()
    def next_open(self):      self._open_step()
    def prenext(self):        self._step()
    def nextstart(self):      self._step()
    def next(self):           self._step()

    def _d(self):
        return self.datas[0].datetime.date(0).isoformat()

    # ---------- 开盘前：先入场（正确序）；缺陷序把当日出场回笼先计入现金 ----------
    def _open_step(self):
        d = self._d()
        broker_cash = self.broker.getcash()
        if self._cash_expect is not None:
            gap = broker_cash - self._cash_expect
            if abs(gap) > self.max_cash_gap:
                self.max_cash_gap = abs(gap)
            self.audit_log.append([d, round(broker_cash, 14), round(self._cash_expect, 14), round(gap, 14)])
            if abs(gap) > 1e-9:
                self.n_cash_audit += 1
                if len(self.audit_bad) < 12:
                    self.audit_bad.append([d, round(broker_cash, 14), round(self._cash_expect, 14), round(gap, 14)])
        # 上一日收盘净值：以「结算后现金 + 持仓按上一根收盘盯市」
        mv_prev = 0.0
        tt = self._cal.index(d)
        for p in self.pos.values():
            j = self._jof.get(p["sym"])
            c = float(self._panelC[tt - 1, j]) if (tt >= 1 and j is not None) else np.nan
            if not (np.isfinite(c) and c > 0):
                c = p["entry_open"]              # 与权威同规则：收盘缺失时按入场价盯市
            mv_prev += p["size"] * c
        self._nav_prev = broker_cash + mv_prev
        prev_d = self._cal[self._cal.index(d) - 1] if d in self._cal and self._cal.index(d) > 0 else None
        if prev_d:
            self.nav[prev_d] = self._nav_prev
            self.depl[prev_d] = (mv_prev / self._nav_prev) if self._nav_prev > 0 else 0.0
        cash = broker_cash
        if self.p.order == "exit_first":
            for (sym, size, xp, _ref) in self.issued.get(d, []):
                cash += size * xp * (1.0 - self.p.cost)      # 缺陷序：开盘即回笼
        self._mirror = cash
        cash_raw = cash                       # 权威等价现金轨迹：仅用于额度判据，不含安全系数
        held = len(self.pos)
        exiting_today = set()
        if self.p.order == "exit_first":
            for (sym, size, xp, _ref) in self.issued.get(d, []):
                exiting_today.add(sym)
            held -= len([s for s in exiting_today if s in self.sym_ref])
        navprev = self._nav_prev if (self._nav_prev and np.isfinite(self._nav_prev)) else 1.0
        for r in self.by_day.get(d, [])[:self.p.k]:
            if held >= self.p.kslot:
                self.n_kslot_break += 1
                break
            if r["sym"] in self.sym_ref and r["sym"] not in exiting_today:
                self.n_dedupe += 1
                continue
            if r["sym"] in exiting_today and r["sym"] in self.sym_ref:
                pass                                        # 缺陷序允许同日再入场（旧序语义）
            # 额度判据**严格按权威规则**（不含安全系数），以逐位复现权威的
            # 「alloc ≤ 1e-12 → break」分支；安全系数只作用于下单规模（见下）
            alloc = min(navprev / self.p.kslot, cash_raw)
            if alloc <= 1e-12:
                self.n_alloc_break += 1
                break
            px = r["entry_open"]
            if not (np.isfinite(px) and px > 0):
                continue
            # 下单量用**backtrader 自己的费用函数**求「可用现金允许的最大规模」（二分）；
            # 这样成交所需的现金由引擎自身口径给出，不会因两边算式不一致而在严格边界上被误判为保证金不足。
            i = self.sym2idx[r["sym"]]
            ci = self.broker.getcommissioninfo(self.datas[i])

            def _need(sz):
                return ci.getoperationcost(sz, px) + ci.getcommission(sz, px)

            cap = min(cash, alloc * (1.0 - SAFETY))   # 上限：实际现金 与 额度×安全系数 取小
            hi = alloc / (px * (1.0 + self.p.cost))
            if _need(hi) > cap:                       # 需要收缩 → 二分（用引擎自身费用函数）
                lo_, hi_ = 0.0, hi
                for _ in range(80):
                    mid = (lo_ + hi_) / 2.0
                    if _need(mid) <= cap:
                        lo_ = mid
                    else:
                        hi_ = mid
                hi = lo_
                self.n_nudge += 1
            size = hi
            o = self.buy(data=self.datas[i], size=size)
            self.issue_log[o.ref] = (d, r["sym"], px, alloc, size, _need(size), cash,
                                     self.broker.getcash())
            self.pos[o.ref] = dict(sym=r["sym"], size=size, entry_open=px,
                                   exit_date=r["exit_date"], exit_px=r["exit_px"])
            self.sym_ref[r["sym"]] = o.ref
            cash -= _need(size)                   # 镜像与实际扣现一致（审计偏差归零）
            cash_raw -= alloc                     # 权威等价轨迹
            self._mirror = cash
            self.entries_list.append([d, r["sym"], round(alloc, 12), round(size, 12)])
            self.n_entries += 1
            held += 1

    # ---------- 收盘：为「次一交易日到期」的持仓发起出场单 ----------
    def _step(self):
        d = self._d()
        t = self._cal.index(d)
        nxt = self._cal[t + 1] if t + 1 < len(self._cal) else None
        if nxt:
            for ref, p in list(self.pos.items()):
                if p["exit_date"] != nxt:
                    continue
                i = self.sym2idx[p["sym"]]
                so = self.sell(data=self.datas[i], size=p["size"], exectype=bt.Order.Close)
                # 两种日序的出场单同为 Close 型（在出场日收盘、以 exit_px 成交）——
                # 两种变体的差异因此**只**剩下资金可用性规则本身（见 _open_step 的镜像与计数），
                # 这正是勘误 E-15 的缺陷本体：当天回笼的钱能否用于当天开盘的买入。
                self.sell_issue[so.ref] = (d, nxt, p["sym"])
                self.issued.setdefault(nxt, []).append((p["sym"], p["size"], p["exit_px"], ref))
        # 现金期望值：入场后现金 + （正确序）当日收盘结算的出场回笼
        c = self._mirror
        if self.p.order == "entry_first":
            for (sym, size, xp, _ref) in self.issued.get(d, []):
                c += size * xp * (1.0 - self.p.cost)
        self._cash_expect = c

    def notify_order(self, o):
        if o.status == o.Completed:
            if o.executed.size < 0:
                self.n_sell_fills += 1
                self.sell_log.append([self.sell_issue.get(o.ref, (None, None, None)), self._d(), o.executed.price])
                hit = False
                for (sym, size, xp, ref) in self.issued.get(self._d(), []):
                    if abs(size - abs(o.executed.size)) < 1e-9 and self.pos.get(ref, {}).get("sym") == sym:
                        self.pos.pop(ref, None)
                        if self.sym_ref.get(sym) == ref:
                            self.sym_ref.pop(sym, None)
                        hit = True
                        break
                if not hit:
                    self.n_sell_unmatched += 1
            else:
                self.n_buy_fills += 1
            return
        if o.status == o.Margin:
            self.n_margin += 1
            self.pos.pop(o.ref, None)                        # 拒单 ⇒ 不得在台账里留幽灵持仓
            for sym, ref in list(self.sym_ref.items()):
                if ref == o.ref:
                    self.sym_ref.pop(sym, None)
            if True:
                try:
                    self.margin_log.append(dict(date=self._d(), sym=o.data._name, isbuy=o.isbuy(),
                                                created_size=o.created.size,
                                                cash_now=self.broker.getcash(),
                                                pos_now=self.broker.getposition(o.data).size,
                                                issue=self.issue_log.get(o.ref)))
                except Exception as e:
                    self.margin_log.append(dict(err=str(e)))
        elif o.status in (o.Rejected, o.Canceled, o.Expired):
            self.n_rejected += 1
            self.pos.pop(o.ref, None)
            for sym, ref in list(self.sym_ref.items()):
                if ref == o.ref:
                    self.sym_ref.pop(sym, None)

    def stop(self):
        d = self._cal[-1]
        cash = self.broker.getcash()
        mv = 0.0
        for p in self.pos.values():
            j = self._jof.get(p["sym"])
            c = float(self._panelC[len(self._cal) - 1, j]) if j is not None else np.nan
            if not (np.isfinite(c) and c > 0):
                c = p["entry_open"]
            mv += p["size"] * c
        self.nav[d] = cash + mv
        self.depl[d] = (mv / (cash + mv)) if (cash + mv) > 0 else 0.0
        self.n_sell_pending_at_end = len(self.pos)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.environ.get("PI_SCRATCH_DIR", "."))
    ap.add_argument("--kslot", type=int, default=20)
    ap.add_argument("--order", choices=("entry_first", "exit_first"), default="entry_first")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--dbg-pseudo", action="store_true")
    a = ap.parse_args()
    cache = pathlib.Path(a.cache)
    if not (cache / "_v_g00_trades.jsonl").exists():
        cache = pathlib.Path(os.environ["PI_SCRATCH_DIR"]) / "x1cache"
    t0 = time.time()
    recs_all = [json.loads(x) for x in (cache / "_v_g00_trades.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    z = np.load(cache / "panel_oos.npz", allow_pickle=True)
    cal_all = [str(x) for x in z["cal"]]
    syms = [str(x) for x in z["syms"]]
    jof = {s: j for j, s in enumerate(syms)}
    iof = {d: i for i, d in enumerate(cal_all)}
    log("[load] 逐笔 %d / 面板 T=%d N=%d (%.1fs)" % (len(recs_all), len(cal_all), len(syms), time.time() - t0))

    if a.start or a.end:
        lo = snap_lo(cal_all, a.start) if a.start else 0
        hi = snap_hi(cal_all, a.end) if a.end else len(cal_all) - 1
        cal = cal_all[lo:hi + 1]
        recs = [r for r in recs_all if iof.get(r["entry_date"], -1) >= lo and iof.get(r["entry_date"], 1 << 30) <= hi
                and iof.get(r["exit_date"], 1 << 30) <= hi]
        O = z["O"][lo:hi + 1]; C = z["C"][lo:hi + 1]
    else:
        cal, recs, O, C = cal_all, recs_all, z["O"], z["C"]
    T = len(cal)
    log("[window] %s ~ %s（%d 日）/ 逐笔 %d / KSLOT=%d / order=%s"
        % (cal[0], cal[-1], T, len(recs), a.kslot, a.order))
    assert len(recs) > 0, "窗口内没有逐笔记录"
    assert all(r["entry_date"] in iof and r["exit_date"] in iof and r["sym"] in jof for r in recs), "日期/标的越界"

    by_day, exit_on = {}, {}
    for r in recs:
        by_day.setdefault(r["entry_date"], []).append(r)
        exit_on.setdefault(r["exit_date"], []).append(r)
    ent = {(r["sym"], r["entry_date"]): r["entry_open"] for r in recs}
    exm = {(r["sym"], r["exit_date"]): r["exit_px"] for r in recs}
    same_day = sum(1 for k in exm if k in ent)
    log("[data] 入场键 %d / 出场键 %d / 同日既出又入 %d" % (len(ent), len(exm), same_day))

    used = sorted({r["sym"] for r in recs})
    log("[feeds] 唯一标的 %d × %d 日 = %.1f 万 bar" % (len(used), T, len(used) * T / 1e4))
    t1 = time.time()
    idx = pd.to_datetime(cal)
    sym2idx, nfo, nfc = {}, 0, 0
    if a.dbg_pseudo:
        import backtrader.brokers.bbroker as _bb
        _DBG = []
        _orig = _bb.BackBroker._execute

        def _shim(self, order, ago=None, price=None, cash=None, position=None, dtcoc=None):
            cin = cash
            bcash0 = None
            if ago is not None:
                try:
                    bcash0 = self.cash
                except Exception:
                    pass
            out = _orig(self, order, ago, price, cash, position, dtcoc)
            try:
                _DBG.append(dict(ref=order.ref, isbuy=order.isbuy(), pseudo=(ago is None),
                                 cash_in=cin, cash_out=out, price=price,
                                 bcash_before=bcash0,
                                 bcash_after=(self.cash if ago is not None else None),
                                 remsize=order.executed.remsize, status=order.getstatusname()))
            except Exception:
                pass
            return out

        _bb.BackBroker._execute = _shim
    cer = bt.Cerebro(stdstats=False, cheat_on_open=True)
    for s in used:
        j = jof[s]
        o, k1 = fill_invalid(O[:, j]); c, k2 = fill_invalid(C[:, j])
        nfo += k1; nfc += k2
        for t, d in enumerate(cal):
            key = (s, d)
            if key in ent:
                o[t] = ent[key]                       # 入场价：只放在 open（买入在开盘成交）
            if key in exm:
                c[t] = exm[key]                       # 出场价：只放在 close（卖出在收盘成交）
                # 注意：799 笔「同日既出又入」的标的在同一根上既要按入场价买、又要按出场价卖，
                # 必须分别落在 open / close 两个字段上，绝不能互相覆盖（否则买入会用出场价成交）。
        sym2idx[s] = len(sym2idx)
        cer.adddata(bt.feeds.PandasData(dataname=pd.DataFrame({"open": o, "close": c}, index=idx),
                                        open="open", high=-1, low=-1, close="close",
                                        volume=-1, openinterest=-1), name=s)
    log("[feeds] 构造 %.1fs（非法值填补 open %d / close %d，均不参与盯市或成交）" % (time.time() - t1, nfo, nfc))

    cer.addstrategy(Ledger, kslot=a.kslot, order=a.order, cost=COST, k=K,
                    by_day=by_day, exit_on=exit_on, sym2idx=sym2idx, cal=cal,
                    panelC=C, jof=jof)
    cer.broker.setcash(1.0)                                # 与自研口径一致：归一化本金
    cer.broker.setcommission(commission=COST, commtype=bt.CommInfoBase.COMM_PERC,
                             stocklike=True, percabs=True)
    # 关闭「提交期伪执行现金校验」：该校验把同一批次内卖单的回笼先记入可用现金（等价于缺陷序的
    # 资金复用），与本次要复核的额度规则不同族，且其边界判定对浮点末位敏感。
    # 额度约束改由本脚本按权威规则自行施加（alloc = min(前一日净值/KSLOT, 结算前现金)）；
    # 真实执行期仍由 broker 校验现金，且真实执行按创建顺序先结算卖单 ⇒ 买入必然足额可行。
    if hasattr(cer.broker, "set_checksubmit"):
        cer.broker.set_checksubmit(False)
    cer.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", timeframe=bt.TimeFrame.Days,
                    riskfreerate=0.0, annualize=True, factor=ANN, stddev_sample=True)
    cer.addanalyzer(bt.analyzers.DrawDown, _name="dd")
    cer.addanalyzer(bt.analyzers.TimeReturn, _name="tr", timeframe=bt.TimeFrame.Days)
    log("[run] Cerebro 运行（runonce=False）...")
    t2 = time.time()
    res = cer.run(runonce=False)
    log("[run] 完成 %.1fs" % (time.time() - t2))
    st = res[0][0] if isinstance(res[0], list) else res[0]   # 本版 cerebro.run() 直接返回策略实例列表
    if a.dbg_pseudo:
        pathlib.Path(str(pathlib.Path(a.out).with_suffix("")) + ".pseudo.json").write_text(
            json.dumps(_DBG, ensure_ascii=False, indent=1, default=_jdef), encoding="utf-8")
        print("[dbg] pseudo 记录 %d 条" % len(_DBG), flush=True)

    days = [d for d in cal if d in st.nav]
    assert len(days) == len(cal), "净值日数不符：%d vs %d" % (len(days), len(cal))
    raw = np.array([st.nav[d] for d in days], float)
    v = raw.copy(); v[0] = 1.0                              # 与自研一致的起点归一法
    nd = len(v) - 1
    ann = (v[-1] / v[0]) ** (ANN / nd) - 1
    pk = np.maximum.accumulate(v); mdd = float((v / pk - 1).min())
    dr = v[1:] / v[:-1] - 1; sd = dr.std(ddof=1)
    sharpe = float(dr.mean() / sd * math.sqrt(ANN)) if sd > 0 else None
    depl = float(np.mean([st.depl.get(d, 0.0) for d in days]))
    tr = st.analyzers.tr.get_analysis()
    out = dict(engine="backtrader-%s" % bt.__version__, order=a.order, kslot=a.kslot,
               window=[days[0], days[-1]], n_days=len(days), n_trades_input=len(recs),
               n_entries=int(st.n_entries), ann=round(ann * 100, 4), mdd=round(mdd * 100, 4),
               sharpe=None if sharpe is None else round(sharpe, 4),
               deploy_pct=round(depl * 100, 4),
               n_margin=int(st.n_margin), n_rejected=int(st.n_rejected), n_nudge=int(st.n_nudge),
               n_dedupe=int(st.n_dedupe), n_kslot_break=int(st.n_kslot_break),
               n_buy_fills=int(st.n_buy_fills), n_sell_fills=int(st.n_sell_fills),
               margin_log=getattr(st, 'margin_log', []),
               audit_bad=getattr(st, 'audit_bad', []),
               entries_list=getattr(st, 'entries_list', []),
               sell_log=getattr(st, 'sell_log', []),
               n_sell_unmatched=int(st.n_sell_unmatched), n_open_at_end=int(st.n_sell_pending_at_end),
               n_alloc_break=int(st.n_alloc_break), same_day_exit_entry=same_day,
               cash_audit_violations=int(st.n_cash_audit), cash_audit_max_gap=float(st.max_cash_gap),
               bt_sharpe_analyzer=(None if tr is None else None),
               bt_sharpe_analyzer_value=(st.analyzers.sharpe.get_analysis().get("sharperatio")),
               n_feeds=len(sym2idx), last_cash=float(cer.broker.getcash()),
               last_value=float(cer.broker.getvalue()))
    ref = (REFERENCE_EXIT_FIRST if a.order == "exit_first" else REFERENCE).get(a.kslot)
    if ref:
        out["reference"] = ref
        out["delta"] = dict(ann=round(out["ann"] - ref["ann"], 4), mdd=round(out["mdd"] - ref["mdd"], 4))
        if "sharpe" in ref and out["sharpe"] is not None:
            out["delta"]["sharpe"] = round(out["sharpe"] - ref["sharpe"], 4)
        if "n_entries" in ref:
            out["delta"]["n_entries"] = out["n_entries"] - ref["n_entries"]
        if "deploy_pct" in ref:
            out["delta"]["deploy_pct"] = round(out["deploy_pct"] - ref["deploy_pct"], 4)
    log("[result] " + json.dumps({k: out[k] for k in ("ann", "mdd", "sharpe", "n_entries", "deploy_pct")}, ensure_ascii=False))
    if "delta" in out:
        log("[delta ] " + json.dumps(out["delta"], ensure_ascii=False))
    if a.out:
        pathlib.Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1, default=_jdef), encoding="utf-8")
        np.save(str(pathlib.Path(a.out).with_suffix("")) + ".nav.npy", v)
        pathlib.Path(str(pathlib.Path(a.out).with_suffix("")) + ".dates.txt").write_text("\n".join(days), encoding="utf-8")
        log("[out] %s (+ .nav.npy / .dates.txt)" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
