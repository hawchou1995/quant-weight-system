# -*- coding: utf-8 -*-
"""R-gushi52-0919 信号 builders（预注册 PRE-REGISTRATION_20260919_gushi52.md 冻结版）
每臂一个纯函数 fn(P)->bool(T,N)；audit_fn 用截断面板重算对拍。
涨停倍率/codes 为静态元数据，模块级缓存，不随截断变化。"""
from pathlib import Path

import numpy as np

# 2026-09-22 修：原为相对路径 "kv_resonance_0913/panel_kv_0913.npz"，而本模块被
# revscreen_regen 以 cwd=仓库根 import → 解析到 <root>/kv_resonance_0913/… 不存在
# → FileNotFoundError → 面板延展未落盘 → 下游 qlch 六臂静默陈旧（事故记录见报告）。
PANEL = str(Path(__file__).resolve().parent / "kv_resonance_0913" / "panel_kv_0913.npz")
_MULT = None


def _mult(N):
    global _MULT
    if _MULT is None:
        c = np.load(PANEL, allow_pickle=True)["codes"]
        m = np.ones(len(c), dtype=np.float64)
        for i, s in enumerate(c):
            s = str(s)
            d = s[2:4]
            if d in ("30", "68"):
                m[i] = 1.20
            elif d in ("60", "00"):
                m[i] = 1.10
            else:
                m[i] = 1.10
        _MULT = m
    return _MULT[:N]


def shift(a, n=1):
    out = np.full_like(a, np.nan)
    if n > 0:
        out[n:] = a[:-n]
    return out


def ma(a, n):
    valid = np.isfinite(a)
    s = np.cumsum(np.where(valid, a, 0.0), axis=0)
    cnt = np.cumsum(valid, axis=0)
    sw = s.copy(); cw = cnt.copy()
    sw[n:] = s[n:] - s[:-n]; cw[n:] = cnt[n:] - cnt[:-n]
    out = np.where(cw >= int(n * 0.6), sw / np.maximum(cw, 1), np.nan)
    out[:n - 1] = np.nan
    return out


def roll(a, n, kind):
    from scipy.ndimage import maximum_filter1d, minimum_filter1d
    valid = np.isfinite(a)
    av = np.where(valid, a, -np.inf if kind == "max" else np.inf)
    o_ = n - 1 - n // 2
    f = maximum_filter1d(av, n, axis=0, origin=o_) if kind == "max" else minimum_filter1d(av, n, axis=0, origin=o_)
    cnt = np.cumsum(valid, axis=0)
    cw = cnt.copy(); cw[n:] = cnt[n:] - cnt[:-n]
    ok = cw >= max(1, n - 2)
    f = np.where(ok & (f > -np.inf) & (f < np.inf), f, np.nan)
    f[:n - 1] = np.nan
    return f


def _base(P):
    C = P["close"].astype(np.float64); O = P["open"].astype(np.float64)
    H = P["high"].astype(np.float64); L = P["low"].astype(np.float64)
    V = P["amount"].astype(np.float64); M = P["mask"].astype(bool)
    T, N = C.shape
    mu = _mult(N)[None, :]
    pc = shift(C, 1)
    with np.errstate(all="ignore"):
        zt = np.round(pc * mu, 2)
        ztclose = (C >= zt - 1e-4) & np.isfinite(zt) & (C > 0)
        touch = (H >= zt - 1e-4) & np.isfinite(zt) & (C > 0)
        r = C / pc - 1.0
        r = np.where(np.isfinite(r), r, np.nan)
        yizi = ztclose & (np.abs(O - C) < 1e-6) & (np.abs(H - C) < 1e-6) & (np.abs(L - C) < 1e-6)
        mkt = np.nanmean(np.where(M, C, np.nan), axis=1)
        mkt = np.where(np.isfinite(mkt), mkt, np.nan)
        idxr = mkt / shift(mkt, 1) - 1.0
        idxr = np.where(np.isfinite(idxr), idxr, np.nan)
    Vm5 = ma(V, 5)
    return dict(C=C, O=O, H=H, L=L, V=V, M=M, T=T, N=N, zt=zt, ztclose=ztclose,
                touch=touch, zhaban=touch & ~ztclose, yizi=yizi, r=r, mkt=mkt,
                idxr=idxr, Vm5=Vm5)


def _f1(B):
    M = B["M"]
    nz = (B["ztclose"] & M).sum(axis=1)
    tsum = (B["touch"] & M).sum(axis=1)
    zsum = (B["zhaban"] & M).sum(axis=1)
    rate = np.divide(zsum, tsum, out=np.ones(len(tsum)), where=tsum > 0)
    yz = shift(B["ztclose"], 1)
    rr = np.where(M & yz, B["r"], np.nan)
    prem = np.nanmean(rr, axis=1)
    ma20i = ma(np.where(np.isfinite(B["mkt"]), B["mkt"], np.nan), 20)
    return (nz >= 30) & (rate < 0.4) & (prem > 0) & (B["mkt"] > ma20i)


def _cnt(a, n):
    v = a.astype(np.float64)
    c = np.cumsum(np.where(np.isfinite(v), v, 0.0), axis=0)
    out = c.copy()
    out[n:] = c[n:] - c[:-n]
    out[:n - 1] = np.nan
    return out


def _ampct(P, V, M):
    """当日成交额全市场分位（行内排名），仅用于 G296f 固定共振过滤。"""
    T, N = V.shape
    out = np.full((T, N), np.nan)
    for i in range(T):
        v = V[i]; m = M[i] & np.isfinite(v)
        if m.sum() < 10:
            continue
        vv = v[m]
        order = np.argsort(vv, kind="stable")
        rk = np.empty(len(vv)); rk[order] = np.arange(len(vv))
        out[i, m] = rk / (len(vv) - 1)
    return out


# ---------------- 15 builders（14 臂，G296 有 BASE/f 两变体） ----------------
def g300(P):
    B = _base(P)
    return (B["r"] >= 0.01) & (B["r"] <= 0.03) & B["M"] & np.isfinite(B["r"])


def g296(P):
    B = _base(P)
    return (B["r"] >= 0.05) & (B["V"] >= 1.5 * B["Vm5"]) & (~B["yizi"]) & B["M"] & np.isfinite(B["r"])


def g296f(P):
    B = _base(P)
    s = g296(P)
    amp = _ampct(P, B["V"], B["M"])
    c20 = B["C"] / shift(B["C"], 20) - 1.0
    return s & (B["C"] >= 3) & (B["C"] <= 100) & (amp >= 0.20) & (amp <= 0.95) & (c20 <= 0.60) & np.isfinite(c20)


def g93a(P):
    B = _base(P)
    return B["ztclose"] & (~B["yizi"]) & _f1(B)[:, None] & B["M"]


def g093b(P):
    B = _base(P)
    return shift(B["ztclose"], 1) & (B["O"] > shift(B["C"], 1)) & (B["C"] < B["O"]) & (B["V"] > 2 * B["Vm5"]) & B["M"]


def g093d(P):
    B = _base(P)
    m20 = ma(B["C"], 20); m10 = ma(B["C"], 10)
    return (m20 > shift(m20, 5)) & (B["C"] > m10) & (B["V"] > B["Vm5"]) & B["M"]


def g67a(P):
    B = _base(P)
    c5 = B["C"] / shift(B["C"], 5) - 1.0
    return shift(c5 < -0.08, 1) & (B["C"] > B["O"]) & (B["r"] > 0.03) & (B["V"] > 1.5 * B["Vm5"]) & B["M"]


def g83a(P):
    B = _base(P)
    return (B["C"] > shift(roll(B["H"], 20, "max"), 1)) & (B["V"] > 1.5 * B["Vm5"]) & B["M"]


def g121a(P):
    B = _base(P)
    m20 = ma(B["C"], 20); m10 = ma(B["C"], 10)
    return (m20 > shift(m20, 5)) & (B["L"] <= m10 * 1.02) & (B["C"] > m20) & B["M"]


def g134a(P):
    B = _base(P)
    hh = roll(B["C"], 20, "max")
    dd = (hh - B["C"]) / hh
    return (_cnt(B["ztclose"], 10) >= 2) & (dd >= 0.20) & (dd <= 0.25) & B["M"]


def g157a(P):
    B = _base(P)
    trig = shift(B["zhaban"], 1) | (shift(B["r"], 1) < -0.04)
    return trig & (B["C"] > B["O"]) & (B["r"] > 0.03) & (B["V"] > 1.5 * B["Vm5"]) & B["M"]


def g200b(P):
    B = _base(P)
    return (B["idxr"] < -0.015)[:, None] & B["ztclose"] & (~B["yizi"]) & B["M"]


def g205g(P):
    B = _base(P)
    c60 = B["C"] / shift(B["C"], 60) - 1.0
    return shift(c60 < 0.30, 1) & B["ztclose"] & (~shift(B["ztclose"], 1)) & (B["V"] > 2 * B["Vm5"]) & B["M"]


def g177a(P):
    B = _base(P)
    with np.errstate(all="ignore"):
        vr = B["V"] / B["Vm5"]
    return (vr >= 1.2) & (vr <= 3) & (B["r"] > 0) & (B["r"] < 0.07) & (B["C"] > ma(B["C"], 20)) & (~B["yizi"]) & B["M"]


def g180a(P):
    B = _base(P)
    return (_cnt(B["ztclose"], 20) >= 2) & B["M"]
