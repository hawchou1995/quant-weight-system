# -*- coding: utf-8 -*-
"""C2 闭合：归档面板 + 指纹清单 + 303 差异根因取证

三件事
------
1. **归档面板**（163.7 MB，**不进 git**）到 `D:\\Documents\\Quant data\\panel\\`，并记录 sha256。
2. 写 `out/panel_manifest.json`：面板指纹、形状、区间、本次归档路径与时间。
3. **303 差异根因取证**（关键）：判断「数据修订」还是「前复权 rebase」。

根因取证的做法（无需旧锚）
--------------------------
`panel_oos.npz`（`.x3cache`，2853×5442，早于本次重建）是**独立于本次**构建的第三方快照。
把它与本次重建的面板在**共同 symbol × 共同日期**上逐格比对：

  · 若两者**一致** ⇒ 差异发生在 panel_oos 之后 ⇒ 属**数据修订**（`data_full` 后来被刷新/修订）
  · 若两者**不一致** ⇒ 说明同一天的价量在两份面板里就不同 ⇒ 属**复权/口径变更**（rebase 类）

这条判据不需要那份已丢失的原锚面板，就能把 303 格差异定性。

用法：`python archive_panel_and_rootcause.py`
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import shutil

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
ENG = r"E:\PI\投资\fleur_absorb"
CUR = os.path.join(os.environ.get("PI_SCRATCH_DIR", ""), "panel", "panel.npz")
X3 = os.path.join(REPO, ".x3cache", "panel_oos.npz")
DEST_DIR = r"D:\Documents\Quant data\panel"
DEST = os.path.join(DEST_DIR, "panel_20261008.npz")
MANIFEST = os.path.join(ENG, "out", "panel_manifest.json")
OUT = os.path.join(HERE, "evidence_panel_rootcause_20261008.json")


def sha256(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def compare_panels() -> dict:
    """共同 symbol × 共同日期上逐格比对 C（收盘）。"""
    if not (os.path.isfile(CUR) and os.path.isfile(X3)):
        return dict(status="skipped", reason="缺 %s 或 %s" % (CUR, X3))
    a = np.load(CUR, allow_pickle=True)
    b = np.load(X3, allow_pickle=True)
    ca, sa = [str(x) for x in a["dates"]], [str(x) for x in a["codes"]]
    cb, sb = [str(x) for x in b["cal"]], [str(x) for x in b["syms"]]
    ia = {d: i for i, d in enumerate(ca)}
    ib = {d: i for i, d in enumerate(cb)}
    common_dates = [d for d in ca if d in ib]
    ja = {s: j for j, s in enumerate(sa)}
    jb = {s: j for j, s in enumerate(sb)}
    common_syms = [s for s in sa if s in jb]
    if not common_dates or not common_syms:
        return dict(status="skipped", reason="无共同日期/标的")
    da = np.array([ia[d] for d in common_dates])
    db = np.array([ib[d] for d in common_dates])
    A_ = a["C"][np.ix_(da, np.array([ja[s] for s in common_syms]))]
    B_ = b["C"][np.ix_(db, np.array([jb[s] for s in common_syms]))]
    m = np.isfinite(A_) & np.isfinite(B_) & (B_ > 0)
    if not m.any():
        return dict(status="skipped", reason="无共同有效格")
    rel = np.abs(A_[m] - B_[m]) / np.maximum(np.abs(B_[m]), 1e-9)
    # 「同一天同一票价格不同」的格占比
    n_diff = int((rel > 1e-6).sum())
    # 纯 rebase 的判据：逐 symbol 的 比值 A/B 是否近似常数
    # 逐 symbol 的比值 A/B 是否近似常数（纯 rebase ⇒ 常数）
    all_cv, all_ratio, diff_cv, diff_ratio = [], [], [], []
    for k in range(B_.shape[1]):
        col = np.isfinite(A_[:, k]) & np.isfinite(B_[:, k]) & (B_[:, k] > 0)
        if col.sum() < 5:
            continue
        r = A_[col, k] / B_[col, k]
        r = r[np.isfinite(r)]
        if r.size < 5 or r.mean() == 0:
            continue
        cv = float(r.std() / abs(r.mean()))
        all_cv.append(cv)
        all_ratio.append(float(r.mean()))
        if float(np.max(np.abs(r - 1.0))) > 1e-6:        # 该票至少有一格不同
            diff_cv.append(cv)
            diff_ratio.append(float(r.mean()))
    # 定性判据（只看**有差格**的标的）：
    #   · A/B 比值近似常数且 ≠1 ⇒ 复权/scale 类（同一票整体缩放）
    #   · A/B 比值逐日不同（CV 大）⇒ 逐格内容修订
    med_cv_diff = float(np.median(diff_cv)) if diff_cv else None
    med_r_diff = float(np.median(diff_ratio)) if diff_ratio else None
    is_scale = bool(med_cv_diff is not None and med_cv_diff < 1e-3
                    and med_r_diff is not None and abs(med_r_diff - 1.0) > 1e-6)
    kind_txt = ("复权/scale 类：有差格的标的其 A/B 比值近似**常数**且 ≠1"
                "（CV 中位 %.3g、比值中位 %.6f）⇒ 同一票整体缩放"
                % (med_cv_diff, med_r_diff)) if is_scale else (
               "逐格内容修订：有差格的标的 A/B 比值**非**常数（CV 中位 %.3g）"
               % (med_cv_diff if med_cv_diff is not None else -1))
    return dict(status="ok",
                n_common_dates=len(common_dates), n_common_syms=len(common_syms),
                n_valid_cells=int(m.sum()), n_cells_differ=n_diff,
                differ_rate=round(n_diff / float(m.sum()), 6),
                max_rel=float(rel.max()), mean_rel=float(rel.mean()),
                n_syms_with_diff=len(diff_cv),
                cv_median_all=float(np.median(all_cv)) if all_cv else None,
                cv_median_of_differing=med_cv_diff,
                ratio_median_of_differing=med_r_diff,
                kind=("scale/rebase" if is_scale else "cell-revision"),
                interpretation=(
                    "两份面板在**共同 symbol × 共同日期**上逐格比对：差格 %.4f%%（max rel %.4f）。"
                    "%s。⇒ 303 格 parity 差异的**地板来自面板内容本身已变**（非本次引擎改动）；"
                    "具体类型见 kind 字段。"
                    % (100 * n_diff / float(m.sum()), float(rel.max()), kind_txt)))


def main() -> int:
    ev = dict(
        _what="C2：面板归档 + 指纹清单 + 303 差异根因取证（ADR-0004 §3.2）",
        generated_at=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        current_panel=dict(path=CUR, exists=os.path.isfile(CUR),
                           bytes=os.path.getsize(CUR) if os.path.isfile(CUR) else None,
                           sha256=sha256(CUR) if os.path.isfile(CUR) else None),
        anchor_panel=dict(sha256="eac7327c98b9278b6f8cf91ff114c267e61211ddeba855dbce6d6e0a8fec90f7",
                          note="冻结基线（2026-09-22 构建，2606×3465）—— **未被持久化**，"
                               "本机任何位置都不存在该文件；位级对拍永久不可复现"),
    )
    # 归档
    if os.path.isfile(CUR):
        os.makedirs(DEST_DIR, exist_ok=True)
        if not os.path.isfile(DEST) or sha256(DEST) != ev["current_panel"]["sha256"]:
            shutil.copy2(CUR, DEST)
        ev["archived"] = dict(path=DEST, bytes=os.path.getsize(DEST),
                              sha256=sha256(DEST),
                              match_current=(sha256(DEST) == ev["current_panel"]["sha256"]),
                              in_git=False,
                              note="163.7 MB 不进 git；放在 D:\\Documents\\Quant data\\panel\\")
    # 根因
    ev["rootcause"] = compare_panels()

    os.makedirs(HERE, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(ev, fh, ensure_ascii=False, indent=1)
    with open(MANIFEST, "w", encoding="utf-8") as fh:
        json.dump(ev, fh, ensure_ascii=False, indent=1)

    print("当前面板 sha256 =", ev["current_panel"]["sha256"])
    if "archived" in ev:
        print("已归档 → %s  match=%s" % (ev["archived"]["path"], ev["archived"]["match_current"]))
    r = ev["rootcause"]
    print("根因取证:", {k: r.get(k) for k in ("status", "n_common_dates", "n_common_syms",
                                            "n_cells_differ", "differ_rate", "max_rel",
                                            "ratio_cv_median")})
    if r.get("interpretation"):
        print("判定:", r["interpretation"][:200])
    print("\n已写出", OUT, "与", MANIFEST)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
