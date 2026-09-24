# -*- coding: utf-8 -*-
"""factorlab_0913 R1: build daily factor panel (main board, 2021-01-04 起)
数据契约: val_em 估值日频(PIT干净) + data_full 日线 + yjbb 季度业绩(法定披露截止日 PIT, ADR-0005)
信息集: 所有因子仅用 T 日及以前信息; fwd return 仅作评估标签。
"""
import numpy as np, pandas as pd, pickle, time, os, sys

BASE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))  # 仓库根（2026-09-24 云端可移植；本机解析恒等）
OUT = os.path.join(BASE, "backtest", "factorlab_0913")
os.makedirs(OUT, exist_ok=True)
START = "2021-01-04"
t0 = time.time()

def log(*a):
    print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)

# ---------- 1. master calendar ----------
idx = pd.read_csv(os.path.join(BASE, "index_000300.csv"), parse_dates=["date"])
cal = idx.loc[idx["date"] >= START, "date"].dt.strftime("%Y-%m-%d").reset_index(drop=True)
ND = len(cal)
di = {d: i for i, d in enumerate(cal)}
log("calendar days:", ND, cal.iloc[0], "->", cal.iloc[-1])
assert ND > 1300

# ---------- 2. val_em wide ----------
val = pd.read_csv(os.path.join(BASE, "data_fundamental/val_em/val_em_all.csv"),
                  dtype={"code": str}, parse_dates=["date"])
val["d"] = val["date"].dt.strftime("%Y-%m-%d")
val = val[val["d"] >= START]
dup = val.duplicated(["d", "code"]).sum()
assert dup == 0, f"val_em dup(d,code)={dup}"
codes = sorted(val["code"].unique())
NC = len(codes)
ci = {c: i for i, c in enumerate(codes)}
log("val_em codes:", NC)

def wide(col):
    p = val.pivot(index="d", columns="code", values=col)
    p = p.reindex(index=cal, columns=codes)
    return p.to_numpy(dtype=np.float64)

pe, pb = wide("pe_ttm"), wide("pb_mrq")
tmv, fmv = wide("total_mv"), wide("float_mv")
close_em = wide("close")
log("val_em wide done")

# ---------- 3. data_full OHLCV ----------
pref = {"6": "sh", "0": "sz", "3": "sz"}
def fname(c):
    return os.path.join(BASE, "data_full", pref[c[0]] + c + ".csv")

open_m = np.full((ND, NC), np.nan)
high_m = np.full((ND, NC), np.nan)
low_m = np.full((ND, NC), np.nan)
close_m = np.full((ND, NC), np.nan)
vol_m = np.full((ND, NC), np.nan)
amt_m = np.full((ND, NC), np.nan)
missing_files, have_file = [], 0
for j, c in enumerate(codes):
    fp = fname(c)
    if not os.path.exists(fp):
        missing_files.append(c); continue
    df = pd.read_csv(fp, parse_dates=["date"])
    df["d"] = df["date"].dt.strftime("%Y-%m-%d")
    df = df.drop_duplicates("d").set_index("d").reindex(cal)
    i = ci[c]
    open_m[:, i] = df["open"].to_numpy(); high_m[:, i] = df["high"].to_numpy()
    low_m[:, i] = df["low"].to_numpy(); close_m[:, i] = df["close"].to_numpy()
    vol_m[:, i] = df["volume"].to_numpy(); amt_m[:, i] = df["amount"].to_numpy()
    have_file += 1
    if have_file % 800 == 0: log("ohlcv files", have_file)
log("ohlcv done: files", have_file, "missing", len(missing_files))

# ---------- 4. ST/退 名单代理 (yjbb 最新期简称; 局限: 现名快照非历史状态) ----------
y = pd.read_csv(os.path.join(BASE, "data_fundamental/yjbb_quarterly.csv"), dtype={"股票代码": str})
name_last = y.sort_values("REPORT_PERIOD").groupby("股票代码")["股票简称"].last()
st_mask = np.array([("ST" in str(name_last.get(c, "")).upper()) or ("退" in str(name_last.get(c, ""))) for c in codes])
log("ST/退 proxy count:", int(st_mask.sum()))

# ---------- 5. yjbb 基本面 PIT 矩阵 (法定披露截止日次一生效日) ----------
DEADLINE = {"0331": "-04-30", "0630": "-08-31", "0930": "-10-31", "1231": "-04-30"}  # 1231 -> 次年
def avail_index(period):
    p = str(period); yy, md = p[:4], p[4:]
    d = f"{yy}{DEADLINE[md]}" if md != "1231" else f"{int(yy)+1}{DEADLINE[md]}"
    d = pd.Timestamp(d)
    after = cal[pd.to_datetime(cal) > d]  # 严格晚于截止日(防披露当晚) → 首个可得交易日
    return di[after.iloc[0]] if len(after) else ND

FMET = {"营业总收入-同比增长": "growth_rev", "净利润-同比增长": "growth_np",
        "销售毛利率": "margin", "净资产收益率": "roe"}
fund = {}
for col, key in FMET.items():
    M = np.full((ND, NC), np.nan)
    y2 = y.dropna(subset=[col])
    for period, g in y2.groupby("REPORT_PERIOD"):  # 升序 -> 晚期覆盖尾部 = as-of 最新期
        ai = avail_index(period)
        if ai >= ND: continue
        for code, v in zip(g["股票代码"], g[col]):
            j = ci.get(code)
            if j is not None: M[ai:, j] = v
    fund[key] = M
    log("fund", key, "first-avail col-mean NaN% row300:", round(float(np.isnan(M[min(300, ND-1)]).mean()*100), 1))

# ---------- 6. 价量因子 (全部仅用 T 日信息) ----------
def D(a): return pd.DataFrame(a, index=cal, columns=codes)
def D_checked(a, name):
    df = pd.DataFrame(a, index=cal, columns=codes)
    ok = np.allclose(df.to_numpy(), a, equal_nan=True)
    log(f"D_checked {name}: faithful={ok} shape={a.shape}")
    if not ok:
        v = df.to_numpy()
        s = v[:, 0].astype(np.float64)
        for nm, arr in [("open", open_m), ("high", high_m), ("low", low_m), ("close", close_m), ("vol", vol_m), ("amt", amt_m)]:
            m = np.isfinite(s) & np.isfinite(arr[:, 0])
            if m.sum() > 50:
                log(f"  C0-vs-{nm}[:,0] match={np.isclose(s[m], arr[m, 0]).mean():.3f}")
    return df

O = D_checked(open_m, "open")
H = D_checked(high_m, "high")
L = D_checked(low_m, "low")
C = D_checked(close_m, "close")
V = D_checked(vol_m, "vol")
A = D_checked(amt_m, "amt")
ret1 = C.pct_change()
with np.errstate(all="ignore"):
    f = {}
    f["ep"] = 1.0 / pe                       # 盈利收益率 (负 pe 排序正确)
    f["bp"] = 1.0 / pb                       # 账面收益
    f["size"] = -np.log(tmv)                 # 小市值
    f["fsize"] = -np.log(fmv)                # 小流通盘
    f["value2"] = None                       # 组合类后填
    f["growth_rev"] = fund["growth_rev"]     # 营收同比高
    f["growth_np"] = fund["growth_np"]       # 净利同比高
    f["margin"] = fund["margin"]
    f["roe"] = fund["roe"]
    f["ret20"] = C.pct_change(20)            # 动量 (主板先验: 反转)
    f["ret5"] = C.pct_change(5)
    f["ret60"] = C.pct_change(60)
    f["vol20"] = -ret1.rolling(20, min_periods=15).std()   # 低波
    f["turn20"] = -(A / fmv).rolling(20, min_periods=15).mean()  # 低换手
    f["amount20"] = -np.log(A.rolling(20, min_periods=15).mean())  # 流动性溢价(小额)
    f["bias20"] = -(C / C.rolling(20).mean() - 1)          # 均线偏离反转
    f["vr5_20"] = -(V.rolling(5).mean() / V.rolling(20).mean())  # 缩量
    f["amp20"] = -((H - L) / C.shift()).rolling(20, min_periods=15).mean()  # 低振幅
    f["dd60"] = -(C / C.rolling(60, min_periods=40).max() - 1)  # 距新高深
    f["mom_sr"] = C.pct_change(20) / (ret1.rolling(20, min_periods=15).std() + 1e-9)  # 稳健动量
    # aroon_osc (25): 100*(days since 25d high/low) — sliding argmax
    W = 25
    sw_h = np.lib.stride_tricks.sliding_window_view(np.vstack([np.full((W-1, C.shape[1]), np.nan), C.to_numpy()]), W, axis=0)
    sw_l = np.lib.stride_tricks.sliding_window_view(np.vstack([np.full((W-1, C.shape[1]), np.nan), L.to_numpy()]), W, axis=0)
    with np.errstate(all="ignore"):
        fin_h = np.isfinite(sw_h).all(axis=2)
        fin_l = np.isfinite(sw_l).all(axis=2)
        up = np.where(fin_h, np.argmax(np.where(np.isfinite(sw_h), sw_h, -np.inf), axis=2) / W * 100, np.nan)
        dn = np.where(fin_l, np.argmin(np.where(np.isfinite(sw_l), sw_l, np.inf), axis=2) / W * 100, np.nan)
    f["aroon_osc"] = up - dn
    # 量价背离: corr(close, vol, 20) 取负
    f["pvc20"] = -C.rolling(20, min_periods=15).corr(V)
    # 共振组合类 (z 相加, 每日截面 z)
    def zs(df):
        a = df.to_numpy(dtype=np.float64)
        mu = np.nanmean(a, axis=1, keepdims=True); sd = np.nanstd(a, axis=1, keepdims=True)
        return (a - mu) / (sd + 1e-12)
    f["value2"] = zs(pd.DataFrame(f["ep"], index=cal, columns=codes)) + zs(pd.DataFrame(f["bp"], index=cal, columns=codes))
    f["size_ep"] = zs(pd.DataFrame(f["size"], index=cal, columns=codes)) + zs(pd.DataFrame(f["ep"], index=cal, columns=codes))
    f["size_rev"] = zs(pd.DataFrame(f["size"], index=cal, columns=codes)) + zs(pd.DataFrame(-C.pct_change(20), index=cal, columns=codes))
    f["ep_lv"] = zs(pd.DataFrame(f["ep"], index=cal, columns=codes)) + zs(pd.DataFrame(-ret1.rolling(20, min_periods=15).std(), index=cal, columns=codes))

FD = {k: (v.to_numpy() if isinstance(v, pd.DataFrame) else v) for k, v in f.items()}
FD = {k: v.astype(np.float32) for k, v in FD.items()}
log("factors built:", len(FD))

# ---------- 7. 调整口径诊断 (data_full vs val_em 收盘价比值) ----------
diag = {}
for c in ["000001", "600519", "000004"]:
    if c not in ci: continue
    j = ci[c]; i1 = di.get("2021-01-04"); i2 = di.get("2023-06-01"); i3 = di.get("2026-09-10")
    row = {}
    for nm, i in [("2021-01-04", i1), ("2023-06-01", i2), ("2026-09-10", i3)]:
        if i is None: continue
        r = close_m[i, j] / close_em[i, j] if (np.isfinite(close_m[i, j]) and np.isfinite(close_em[i, j]) and close_em[i, j]) else np.nan
        row[nm] = round(float(r), 4) if np.isfinite(r) else None
    diag[c] = row
log("adjust diag (data_full/val_em):", diag)

# ---------- 8. save ----------
panel = dict(cal=cal.to_numpy(), codes=np.array(codes), st_mask=st_mask,
             open=open_m.astype(np.float32), high=high_m.astype(np.float32), low=low_m.astype(np.float32),
             close=close_m.astype(np.float32), vol=vol_m.astype(np.float32), amt=amt_m.astype(np.float32),
             pe=pe.astype(np.float32), pb=pb.astype(np.float32), tmv=tmv.astype(np.float32),
             fmv=fmv.astype(np.float32), factors=FD, adj_diag=diag)
with open(os.path.join(OUT, "panel_0913.pkl"), "wb") as fh:
    pickle.dump(panel, fh, protocol=4)
log("saved panel_0913.pkl", round(os.path.getsize(os.path.join(OUT, "panel_0913.pkl"))/1e6), "MB")

# ---------- 9. assertions ----------
assert open_m.shape == (ND, NC) and len(FD) == 25
cov_o = np.isfinite(open_m).mean(); cov_pe = np.isfinite(pe).mean()
log(f"coverage open={cov_o:.3f} pe={cov_pe:.3f}")
assert cov_o > 0.5 and cov_pe > 0.5
# 前视自检: ret20[t] 只应依赖 close[<=t]（选无停牌 NaN 的窗口避免 fill 语义差异）
log("final C fidelity:", np.allclose(C.to_numpy(), close_m, equal_nan=True))
assert np.allclose(C.to_numpy(), close_m, equal_nan=True), "C mutated during factor computation!"
c0 = close_m[:, ci[codes[0]]]
k = next(kk for kk in range(60, 800) if np.isfinite(c0[kk-20:kk+1]).all())
mv = c0[k]/c0[k-20]-1; pv = C.pct_change(20).to_numpy()[k, 0]
cn = C.to_numpy()
log("check codes0=", codes[0], "cols0=", C.columns[0], "k=", k)
log("c0[k-20],c0[k]:", c0[k-20], c0[k], "| C:", cn[k-20, 0], cn[k, 0])
log("col0 equal?", np.allclose(np.nan_to_num(c0), np.nan_to_num(cn[:, 0])),
    "shares_mem:", np.shares_memory(cn, close_m),
    "index[k]:", C.index[k], cal.iloc[k])
bad = np.argwhere(~np.isclose(np.nan_to_num(c0), np.nan_to_num(cn[:, 0]), equal_nan=True)).ravel()
log("diverge rows:", bad[:10], "n_bad:", len(bad))
assert abs(mv - pv) < 1e-9
log("ALL ASSERTIONS PASSED")
