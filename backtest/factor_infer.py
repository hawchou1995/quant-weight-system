# -*- coding: utf-8 -*-
"""factor_infer — 把"事件级显著性"换成"按天聚类"的诚实版本（R-infer-0918）

为什么要它
  一天之内的几百笔交易共享同一波行情；同一只票的连续信号，持有窗口互相重叠。
  把它们当成互不相干的独立样本，算出来的显著性倍数会虚高好几倍。
  本工具按"天"重新聚类，给出三个数字：虚高倍数、有效样本量、分块自助区间。

用法
  python factor_infer.py infer <sig.npz> [--key sig] [--hold 10] [--block 20] [--B 1000]
  python factor_infer.py selftest
"""
import sys
import json
import numpy as np
from factor_gate import load_panel

HOLD = 10
COST = 0.0020   # 单边往返成本假设 20bp


def load_sig(path, key=None):
    D = np.load(path)
    if key is None:
        key = "sig" if "sig" in D.files else D.files[0]
    return D[key].astype(bool)


def market_bm(P, hold=HOLD):
    """全市场等权同期收益（与信号完全同口径），用作超额基准。"""
    O = P["open"].astype(np.float64)
    C = P["close"].astype(np.float64)
    M = P["mask"]
    T, N = O.shape
    e = np.full((T, N), np.nan)
    x = np.full((T, N), np.nan)
    e[: T - 1] = O[1:]
    x[: T - 1 - hold] = C[1 + hold:]
    with np.errstate(all="ignore"):
        R = x / e - 1.0
    R = np.where(np.isfinite(R), R, np.nan)
    V = np.where(M, R, np.nan)
    num = np.nansum(V, axis=1)
    den = np.sum(np.isfinite(V), axis=1)
    return np.divide(num, den, out=np.full(T, np.nan), where=den > 0)


def trade_returns(P, sig, hold=HOLD):
    """信号日 t 收盘出信号 -> t+1 开盘买入 -> t+1+hold 收盘卖出。"""
    O = P["open"].astype(np.float64)
    C = P["close"].astype(np.float64)
    M = P["mask"]
    T, N = O.shape
    e = np.full((T, N), np.nan)
    x = np.full((T, N), np.nan)
    e[: T - 1] = O[1:]
    x[: T - 1 - hold] = C[1 + hold:]
    r = x / e - 1.0
    ok = sig & M & np.isfinite(r)
    day, stk = np.nonzero(ok)
    return r[ok], day, stk


def naive_t(r):
    """假装每笔交易都是独立样本。"""
    n = int(r.size)
    if n < 2:
        return {"mean": float("nan"), "t": float("nan"), "n": n, "se": float("nan")}
    m = float(r.mean())
    sd = float(r.std(ddof=1))
    se = sd / np.sqrt(n)
    t = m / se if se > 0 else float("nan")
    return {"mean": m, "t": t, "n": n, "se": se}


def cluster_t(r, day, G):
    """按天聚类估标准误（CR0 + G/(G-1) 小样本修正）。点估计与事件级完全相同，只改误差。"""
    n = int(r.size)
    if n < 2:
        return {"mean": float("nan"), "t": float("nan"), "n": n,
                "n_groups": 0, "se": float("nan")}
    m = float(r.mean())
    u = r - m
    s = np.bincount(day, weights=u, minlength=G)
    V = float((s ** 2).sum()) / (n ** 2)
    if G > 1:
        V *= G / (G - 1.0)
    se = float(np.sqrt(V))
    t = m / se if se > 0 else float("nan")
    return {"mean": m, "t": t, "n": n, "n_groups": int(G), "se": se}


def daily_mean(r, day, G):
    """把同一天的交易先等权平均，得到"一天一个观测"的序列。"""
    s = np.bincount(day, weights=r, minlength=G)
    c = np.bincount(day, minlength=G)
    dm = np.divide(s, c, out=np.zeros(G), where=c > 0)
    return dm[c > 0]


def block_boot(dm, block=20, B=1000, seed=20260918):
    """连续天数分块重采样，保留块内的相关性结构。"""
    rng = np.random.default_rng(seed)
    k = int(dm.size)
    if k < 2 * block:
        return None
    nb = int(np.ceil(k / block))
    hi = k - block
    off = np.arange(block)
    means = np.empty(B)
    for b in range(B):
        st = rng.integers(0, hi + 1, nb)
        idx = (st[:, None] + off[None, :]).ravel()[:k]
        means[b] = dm[idx].mean()
    return means


def boot_p(means, side):
    """加一修正：p 永远不可能是 0。"""
    B = int(means.size)
    k = int((means <= 0).sum()) if side == "pos" else int((means >= 0).sum())
    return (1 + k) / (B + 1)


def infer(sig_path, key=None, hold=HOLD, block=20, B=1000, seed=20260918,
          excess=False):
    P = load_panel()
    sig = load_sig(sig_path, key)
    T, N = P["close"].shape
    if sig.shape != (T, N):
        raise SystemExit("信号形状与面板不符: %s vs %s" % (sig.shape, (T, N)))
    r, day, stk = trade_returns(P, sig, hold)
    if excess:
        b = market_bm(P, hold)
        r = r - COST - b[day]
        g = np.isfinite(r)
        r, day = r[g], day[g]
    if r.size < 2:
        raise SystemExit("有效交易不足: %d" % r.size)
    nv = naive_t(r)
    cl = cluster_t(r, day, T)
    dm = daily_mean(r, day, T)
    infl = abs(nv["t"] / cl["t"]) if np.isfinite(cl["t"]) and cl["t"] != 0 else float("nan")
    eff_n = nv["n"] / (infl ** 2) if np.isfinite(infl) and infl > 0 else float("nan")
    bm = block_boot(dm, block, B, seed)
    out = {
        "sig": sig_path,
        "metric": "超额(扣20bp成本与大盘同期)" if excess else "每笔原始收益",
        "hold": hold,
        "n_trades": nv["n"],
        "n_days_active": int(dm.size),
        "avg_trades_per_day": float(nv["n"] / max(1, dm.size)),
        "mean_ret_pct": float(nv["mean"] * 100),
        "se_naive_pct": float(nv["se"] * 100),
        "se_cluster_pct": float(cl["se"] * 100),
        "t_naive": float(nv["t"]),
        "t_cluster": float(cl["t"]),
        "t_inflation": float(infl),
        "eff_n": float(eff_n),
        "daily_mean_pct": float(dm.mean() * 100),
        "daily_median_pct": float(np.median(dm) * 100),
        "daily_pos_share": float((dm > 0).mean()),
    }
    if bm is not None:
        out["boot_block"] = block
        out["boot_B"] = B
        out["boot_ci_low_pct"] = float(np.percentile(bm, 2.5) * 100)
        out["boot_ci_high_pct"] = float(np.percentile(bm, 97.5) * 100)
        out["boot_p_pos"] = float(boot_p(bm, "pos"))
        out["boot_p_neg"] = float(boot_p(bm, "neg"))
    return out


def _plain(o):
    """人话版输出——给不看 JSON 的人。"""
    L = []
    L.append("信号文件        : %s" % o["sig"])
    L.append("交易笔数        : %s 笔（分布在 %s 个交易日，平均每天 %s 笔）"
             % (format(o["n_trades"], ","), format(o["n_days_active"], ","),
                round(o["avg_trades_per_day"], 1)))
    L.append("口径            : %s" % o.get("metric", "-"))
    L.append("每笔平均        : %+.3f%%" % o["mean_ret_pct"])
    L.append("")
    L.append("拿每笔当独立样本算的显著性倍数 : %+.2f" % o["t_naive"])
    L.append("按天聚类后重算的显著性倍数     : %+.2f" % o["t_cluster"])
    L.append("→ 前者把后者放大了 %.2f 倍" % o["t_inflation"])
    L.append("→ 真正互不相干的样本量只有 %s 笔（不是 %s 笔）"
             % (format(int(round(o["eff_n"])), ","), format(o["n_trades"], ",")))
    L.append("")
    if "boot_p_pos" in o:
        L.append("连续 %d 天为一组重采样 %d 次，均值区间 %.3f%% ~ %.3f%%"
                 % (o["boot_block"], o["boot_B"], o["boot_ci_low_pct"], o["boot_ci_high_pct"]))
        L.append("正收益概率 %.4f / 负收益概率 %.4f（已做加一修正，不会是 0）"
                 % (o["boot_p_pos"], o["boot_p_neg"]))
    L.append("")
    L.append("按天先平均再看：日均 %+.3f%%，中位 %+.3f%%，上涨天数占比 %.1f%%"
             % (o["daily_mean_pct"], o["daily_median_pct"], o["daily_pos_share"] * 100))
    return "\n".join(L)


def _synth(rng, D, m, icc, mu=0.0, sd_tot=0.05):
    """造一份"同一天有共同涨跌"的合成数据。icc=0 表示完全没有共同涨跌。"""
    sd_d = np.sqrt(icc) * sd_tot
    sd_e = np.sqrt(1.0 - icc) * sd_tot
    shock = rng.normal(0.0, sd_d, D)
    day = np.repeat(np.arange(D), m)
    r = mu + shock[day] + rng.normal(0.0, sd_e, D * m)
    return r, day, D


def selftest():
    rng = np.random.default_rng(20260918)
    rep = {}

    # A 正对照：确实存在"同一天共同涨跌"——事件级必须被放大，聚类后必须压回去
    r, day, G = _synth(rng, 800, 60, 0.80, mu=0.010)
    nv, cl = naive_t(r), cluster_t(r, day, G)
    micc = abs(nv["t"] / cl["t"])
    rep["A 正对照(共同涨跌 icc=0.8)"] = {
        "事件级倍数": round(nv["t"], 2), "聚类后倍数": round(cl["t"], 2),
        "放大倍数": round(micc, 2), "理论放大": round(np.sqrt(1 + 59 * 0.8), 2),
    }

    # B 负对照：完全没有共同涨跌——两者必须几乎一样
    r2, day2, G2 = _synth(rng, 800, 60, 0.0, mu=0.010)
    nv2, cl2 = naive_t(r2), cluster_t(r2, day2, G2)
    b_ratio = abs(nv2["t"] / cl2["t"])
    rep["B 负对照(无共同涨跌)"] = {
        "事件级倍数": round(nv2["t"], 2), "聚类后倍数": round(cl2["t"], 2),
        "放大倍数": round(b_ratio, 3),
    }

    # C 零假设误报率：真均值=0 但确有共同涨跌 —— 事件级会大量谎报，聚类后必须回到 5% 附近
    NREP, D3, M3, ICC3 = 200, 400, 50, 0.5
    fp_n = fp_c = 0
    for _ in range(NREP):
        rr, dd, GG = _synth(rng, D3, M3, ICC3, mu=0.0)
        if abs(naive_t(rr)["t"]) > 1.96:
            fp_n += 1
        if abs(cluster_t(rr, dd, GG)["t"]) > 1.96:
            fp_c += 1
    rep["C 零假设误报率(真均值=0)"] = {
        "重复次数": NREP,
        "事件级谎报率": round(fp_n / NREP, 4),
        "聚类后谎报率": round(fp_c / NREP, 4),
        "理论放大": round(np.sqrt(1 + (M3 - 1) * ICC3), 2),
    }

    # D 标准误对账：聚类标准误必须吻合解析解 σ_d²/D + σ_e²/(D·m)
    D4, M4, ICC4, SD4 = 800, 60, 0.80, 0.05
    r4, day4, G4 = _synth(rng, D4, M4, ICC4, mu=0.0, sd_tot=SD4)
    cl4 = cluster_t(r4, day4, G4)
    theory = np.sqrt((ICC4 * SD4 ** 2) / D4 + ((1 - ICC4) * SD4 ** 2) / (D4 * M4))
    err = abs(cl4["se"] / theory - 1.0)
    rep["D 标准误对账"] = {
        "聚类标准误": round(cl4["se"] * 100, 5), "理论标准误": round(theory * 100, 5),
        "相对误差": round(err, 4),
    }

    ok = True
    chk = []
    c1 = micc >= 3.0
    chk.append(("A 正对照检出虚高(>=3倍)", c1))
    ok &= c1
    c2 = b_ratio <= 1.15
    chk.append(("B 负对照不虚高(<=1.15倍)", c2))
    ok &= c2
    c3 = (fp_n / NREP) > 0.40
    chk.append(("C1 事件级确实大量谎报(>40%)", c3))
    ok &= c3
    c4 = (fp_c / NREP) < 0.12
    chk.append(("C2 聚类后谎报率被压回(<12%)", c4))
    ok &= c4
    c5 = err < 0.25
    chk.append(("D 标准误吻合理论(<25%误差)", c5))
    ok &= c5

    print("=" * 62)
    print("factor_infer 自检")
    print("=" * 62)
    for k, v in rep.items():
        print("\n[%s]" % k)
        for kk, vv in v.items():
            print("   %-14s %s" % (kk, vv))
    print("\n" + "-" * 62)
    for name, passed in chk:
        print("  %s  %s" % ("PASS" if passed else "FAIL", name))
    print("-" * 62)
    print("总判: %s" % ("全过 PASS" if ok else "有 FAIL"))
    return ok


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return
    if a[0] == "selftest":
        selftest()
        return
    if a[0] != "infer":
        print(__doc__)
        return
    p = a[1]
    key = a[a.index("--key") + 1] if "--key" in a else None
    hold = int(a[a.index("--hold") + 1]) if "--hold" in a else HOLD
    blk = int(a[a.index("--block") + 1]) if "--block" in a else 20
    B = int(a[a.index("--B") + 1]) if "--B" in a else 1000
    o = infer(p, key=key, hold=hold, block=blk, B=B)
    print(_plain(o))
    if "--json" in a:
        print(json.dumps(o, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
