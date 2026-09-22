# -*- coding: utf8 -*-
"""revscreen_regen — 反向筛回避资产日更（R-daban-negscreen-0919 · 2026-09-20 用户批准建）

把 A5 反向筛闸门的资产（kv 面板 → 10 臂信号 → block9/block10 回避掩码）随 data_full 推进。
不建这一步，闸门覆盖会停在资产末日，09-14 起「闸门开了但拦不到东西」。

设计原则：**历史行不可变**。
  1. 只把新增交易日追加进面板；历史 2599 行从既有资产逐位保留。
  2. 臂信号在扩展面板上重算后，历史行与既有 sig 对拍（DRIFT 闸）。
  3. 掩码重算后，历史行强制写回既有已验证值（DRIFT 闸）。
  4. 任一 DRIFT > 0 → **立即中止**，保留旧资产，退出码非零，日志 `!!` 告警。
     这防止 data_full 历史复权再次被修订时， silently 改写已验证决策
     （2026-09-20 实测：data_full 历史价在 09-13 后被复权重述，1229/3960 股 ±1%，
      按新基重建的面板与事件表 91/975 笔不符，旧基 975/975 吻合）。

口径：臂信号日 s 起，该股在 [s, s+K+1] 回避；入场日 D 命中 ⇔ ∃s≤D-1 且 D-s≤K+1。
只拦新开仓；面板未覆盖（北交所/已退市/缺失）→ 不拦（保守，宁漏不错）。

用法：python revscreen_regen.py [--dry-run]   （无新日期时正常退出 0，不写盘）
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
BK = Path(__file__).resolve().parent
PANEL = BK / "kv_resonance_0913" / "panel_kv_0913.npz"
IDX = BASE / "index_000300.csv"
DATA = BASE / "data_full"
ARMS = {"g300": 1, "g177a": 1, "g093d": 10, "g121a": 5, "g83a": 3,
        "g205g": 1, "g93a": 1, "g200b": 1, "g134a": 5, "g157a": 5}
ARMS9 = {k: v for k, v in ARMS.items() if k != "g157a"}
DRY = "--dry-run" in sys.argv
FORCE = "--force" in sys.argv      # 面板已最新时仍强制重算（fwd 回填等自愈场景）
t0 = time.time()


def log(*a):
    print("[%6.1fs]" % (time.time() - t0), *a, flush=True)


def die(msg):
    print("!! revscreen_regen 中止: %s" % msg, flush=True)
    sys.exit(4)


# ---------- 1. 目标日历 vs 面板日历 ----------
idx = pd.read_csv(IDX, parse_dates=["date"])
cal_new = [d.strftime("%Y-%m-%d") for d in idx.loc[idx["date"] >= "2016-01-04", "date"]]
z = np.load(PANEL, allow_pickle=True)
cal_old = [str(x) for x in z["cal"]]
_FILL = {}          # fwd* 回填格数（R-ocr-fix-0922）
STAGE = []          # 待提交资产 [(path, writer)]，全部校验通过后一次性落盘
codes = [str(x) for x in z["codes"]]
n_old = len(cal_old)

if cal_new[:n_old] != cal_old:
    die("面板日历不是指数日历的前缀（历史日历被改动），拒绝推进")
if len(cal_new) == n_old and not FORCE:
    log("已最新（%s），无需重生成" % cal_old[-1])
    sys.exit(0)
new_dates = cal_new[n_old:]
if new_dates:
    log("面板 %d 行 → 目标 %d 行，新增 %d 个交易日: %s"
        % (n_old, len(cal_new), len(new_dates), new_dates[0] + "~" + new_dates[-1]))
else:
    log("面板 %d 行 → 目标 %d 行，**无新增交易日**（--force 自愈重算：只补历史缺口，不推进日历）"
        % (n_old, len(cal_new)))
if DRY:
    log("--dry-run，不写盘")
    sys.exit(0)

# ---------- 2. 只读新增日期的 OHLCV ----------
T, N = len(cal_new), len(codes)
rows = {d: k for k, d in enumerate(new_dates)}
O = np.full((T, N), np.nan); H = np.full((T, N), np.nan)
L = np.full((T, N), np.nan); C = np.full((T, N), np.nan)
A = np.full((T, N), np.nan)
for j, c in enumerate(codes):
    p = DATA / (c + ".csv")
    if not p.exists():
        continue
    try:
        df = pd.read_csv(p, usecols=["date", "open", "high", "low", "close", "amount"])
    except Exception:
        continue
    d = df["date"].astype(str).values
    m = np.array([x in rows for x in d])
    if not m.any():
        continue
    k = n_old + np.array([rows[x] for x in d[m]])
    O[k, j] = df["open"].values[m]; H[k, j] = df["high"].values[m]
    L[k, j] = df["low"].values[m]; C[k, j] = df["close"].values[m]
    A[k, j] = df["amount"].values[m]
_filled = int(np.isfinite(C[n_old:]).sum())
_ref = int(np.isfinite(np.asarray(z["close"])[n_old - 1]).sum()) if n_old > 0 else 0
log("新增行填充完成: close 非空 %d 格（参照上一交易日 %d 格）" % (_filled, _ref))
if new_dates and _filled < 0.5 * max(_ref, 1) * len(new_dates):
    die("新增行填充不足（%d 格，预期约 %d）→ 索引或数据源异常，拒绝写盘"
        % (_filled, _ref * len(new_dates)))

# ---------- 3. 组装扩展面板：历史行逐位保留，新行用刚读的数据 ----------
# 注意：mask / 派生因子必须在「历史行+新行」齐备的帧上算。
# 早期版本只把新行填进全 NaN 帧 → amt20 滚动均值全 NaN → 新行 mask 恒 False → 臂信号少 0.3%。
_old = {k: np.asarray(z[k]) for k in z.files}
_of = np.vstack([_old["open"], O[n_old:]])
_hf = np.vstack([_old["high"], H[n_old:]])
_lf = np.vstack([_old["low"], L[n_old:]])
_cf = np.vstack([_old["close"], C[n_old:]])
_af = np.vstack([_old["amount"], A[n_old:]])
Cd = pd.DataFrame(_cf); Od = pd.DataFrame(_of); Hd = pd.DataFrame(_hf)
Ld = pd.DataFrame(_lf); Ad = pd.DataFrame(_af)
amt20 = Ad.rolling(20, min_periods=10).mean()
listed = Cd.notna().cumsum()
mask_new = ((listed >= 120) & (Cd >= 1.5) & (amt20 >= 1e7)).values
_nmask = int(mask_new[n_old:].sum())
log("新行 mask 生效 %d 格（若为 0 说明均量窗口断裂）" % _nmask)
if new_dates and _nmask < 1000:
    die("新行可交易掩码几乎全空（%d 格）→ 均量/上市窗口断裂，拒绝写盘"
        % int(mask_new[n_old:].sum()))

out = {"cal": np.array(cal_new, dtype=object),
       "codes": np.array(codes, dtype=object),
       "ind_names": z["ind_names"], "ind_id": np.asarray(z["ind_id"])}
for k in z.files:
    if k in out:
        continue
    old = np.asarray(z[k])
    if k == "mask":
        full = np.vstack([old, mask_new[n_old:].astype(old.dtype)])
    elif k in ("open", "high", "low", "close", "amount"):
        new = {"open": O, "high": H, "low": L, "close": C, "amount": A}[k]
        full = np.vstack([old, new[n_old:].astype(old.dtype)])
    else:
        # 派生/前视标签： arms 不用，按同公式在全帧重算后历史行写回，保持面板自洽
        if k == "ret20":
            f = (Cd / Cd.shift(20) - 1.0).values
        elif k == "amt_ratio20":
            f = (Ad / Ad.rolling(20, min_periods=10).mean().shift(1)).values
        elif k == "longbar":
            pc = Cd.shift(1)
            tr = pd.concat([(Hd - Ld).stack(), (Hd - pc).abs().stack(),
                            (Ld - pc).abs().stack()], axis=1).max(axis=1).unstack()
            atr = tr.rolling(20, min_periods=10).mean().shift(1)
            f = ((Cd - Od) / atr.replace(0, np.nan)).values
        elif k == "breakout60":
            f = (Cd / Hd.rolling(60, min_periods=30).max().shift(1) - 1.0).values
        elif k in ("fwd5", "fwd10", "fwd20"):
            sh = {"fwd5": 6, "fwd10": 11, "fwd20": 21}[k]
            f = (Od.shift(-sh) / Od.shift(-1) - 1.0).values
        else:
            full = old
            out[k] = full
            continue
        full = np.vstack([old, f[n_old:].astype(old.dtype)])
        if k in ("fwd5", "fwd10", "fwd20"):
            # R-ocr-fix-0922（OCR 发现3）：fwd 标签在追加时未来K线尚不存在 → 存 NaN；
            #   而历史行按契约"不可变"，导致这批 NaN **永不回填**，且每轮 regen 继续累积。
            #   回填判据恒为「存储值为 NaN 且全帧重算有值」——已核验的非 NaN 历史值一个不动。
            _m = ~np.isfinite(full[:n_old]) & np.isfinite(f[:n_old])
            if _m.any():
                full[:n_old][_m] = f[:n_old][_m]
                _FILL[k] = int(_m.sum())
    out[k] = full
# ★ 面板不再在此处落盘（原为发现1：写盘早于 DRIFT 闸 → 漂移时旧资产已被覆盖）
STAGE.append((PANEL, lambda _o=dict(out): np.savez(PANEL, **_o)))

# ---------- 4. 重算臂信号 + DRIFT 闸 ----------
sys.path.insert(0, str(BK))
import factor_gate as FG
import _tmp_0919_g52_arms as AR

P = FG.load_panel()
sigs = {}
for arm, K in ARMS.items():
    sig = np.asarray(getattr(AR, arm)(P), dtype=bool)
    f = BK / ("_tmp_0919_g52_sig_%s.npz" % arm)
    old = np.load(f, allow_pickle=True)["sig"]
    if old.shape[0] > n_old:
        die("%s 既有 sig 行数 %d 超过面板历史行 %d，资产状态异常" % (arm, old.shape[0], n_old))
    if old.shape[0] == n_old:
        if not bool((sig[:n_old] == old).all()):
            d = int((sig[:n_old] != old).sum())
            die("%s 历史信号漂移 %d 格 → data_full 历史基已变，拒绝改写已验证决策" % (arm, d))
        _cmp = "历史 %d 行逐位一致" % n_old
    else:
        # R-ocr-fix-0922（OCR 发现4）：原实现对拍没跑也打印「逐位一致」= 审计假阳性。
        #   现在只在真的比过之后才敢说一致，否则明写跳过。
        _cmp = ("既有 sig 仅 %d 行 < 面板历史 %d 行 → **跳过历史对拍**（首次扩窗，无基准）"
                % (old.shape[0], n_old))
    sigs[arm] = sig
    # ★ 只入队，不落盘（原为发现2：循环内逐个覆盖 → 后臂漂移时前臂已换，资产集行数不一致）
    STAGE.append((f, (lambda _p=f, _s=sig: np.savez_compressed(_p, sig=_s))))
    log("  %-7s 信号 %d 格，%s" % (arm, int(sig.sum()), _cmp))


# ---------- 5. 重建掩码 + DRIFT 闸 ----------
def active(sig, K):
    cs = np.cumsum(sig.astype(np.int32), axis=0)
    csp = np.vstack([np.zeros((1, sig.shape[1]), dtype=np.int32), cs])
    o = np.zeros(sig.shape, dtype=bool)
    for t in range(sig.shape[0]):
        j = t - (K + 1)
        o[t] = (csp[t] - (csp[j] if j >= 0 else 0)) > 0
    o &= sig.any(axis=0)[None, :]
    return o


for name, ak in (("9", ARMS9), ("10", ARMS)):
    full = np.zeros((T, N), dtype=bool)
    for arm, K in ak.items():
        full |= active(sigs[arm], K)
    f = BK / ("_tmp_0919_g52_block%s.npz" % name)
    old = np.load(f, allow_pickle=True)
    oldm = np.asarray(old["blocked"]).astype(bool)
    oldcal = [str(x) for x in old["cal"]]
    if oldm.shape[0] > n_old:
        die("block%s 既有行数超过面板历史行，资产状态异常" % name)
    if oldm.shape[0] == n_old:
        drift = int((full[:n_old] != oldm).sum())
        if drift:
            die("block%s 历史行重算漂移 %d 格，拒绝改写已验证决策" % (name, drift))
        full[:n_old] = oldm          # 强制写回（双保险）
    if oldcal[:min(len(oldcal), n_old)] != cal_old[:len(oldcal)]:
        die("block%s 既有 cal 与面板历史日历不一致" % name)
    STAGE.append((f, (lambda _p=f, _b=full, _c=old["codes"]:
                      np.savez_compressed(_p, blocked=_b, codes=_c,
                                          cal=np.array(cal_new, dtype=object)))))
    _nb = (full[n_old:].sum(axis=1).mean() if len(new_dates) else 0.0)
    log("block%s 已入队：历史 %d 行 0 漂移，新 %d 行日均回避 %s"
        % (name, n_old, len(new_dates), ("%.0f 只" % _nb) if len(new_dates) else "—（无新增行）"))

# ---------- 6. 覆盖自检 ----------
sys.path.insert(0, str(BASE.parent / "打板系统A5实验_20260827"))
import importlib.util
sp = importlib.util.spec_from_file_location(
    "rev_screen", BASE.parent / "打板系统A5实验_20260827" / "rev_screen.py")
rs = importlib.util.module_from_spec(sp)
sp.loader.exec_module(rs)
# ---------- 6b. 提交（全部校验已通过）+ 覆盖自检 + 失败整体回滚 ----------
# R-ocr-fix-0922（OCR 发现1）：原实现 np.savez(PANEL) 在 DRIFT 闸之前，
#   docstring 承诺「任一 DRIFT > 0 → 立即中止，保留旧资产」实际做不到——闸响时旧面板已没了。
#   现改为：先算 → 先校 → 全部通过才一次性提交；提交中任何失败按备份整体回滚。
_BAK = []
_COMMITTED = []
try:
    for _p, _fn in STAGE:
        if _p.exists():
            _b = _p.parent / (_p.name + ".precommit")
            _b.write_bytes(_p.read_bytes())
            _BAK.append((_p, _b))
        _fn()
        _COMMITTED.append(_p)
        log("  ✅ 提交 %s" % _p.name)
    s = rs.stats(cal_new[-1])
    log("闸门覆盖自检: 最新交易日 %s covered=%s 回避 %s 只 / 宇宙 %s"
        % (cal_new[-1], s.get("covered"), s.get("avoided_symbols"), s.get("universe")))
    if not s.get("covered"):
        raise RuntimeError("写回后最新交易日仍未覆盖")
except BaseException as _e:
    for _p in _COMMITTED:
        _b = _p.parent / (_p.name + ".precommit")
        if _b.exists():
            _p.write_bytes(_b.read_bytes())
            log("  ↩ 已回滚 %s" % _p.name)
    _n = len(_COMMITTED)
    if isinstance(_e, SystemExit):
        raise
    die("提交阶段失败（已回滚 %d 个资产）: %r" % (_n, _e))
for _p, _b in _BAK:
    _b.unlink(missing_ok=True)

json.dump({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "n_old": n_old,
           "n_new": T, "new_dates": new_dates, "arms": list(ARMS),
           "fwd_backfill": _FILL},
          open(BK / "revscreen_regen_state.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
log("fwd 标签回填: %s" % (_FILL if _FILL else "无（%d 行历史标签需补但全帧重算仍缺未来K线）" % 0))
log("REGEN DONE")
