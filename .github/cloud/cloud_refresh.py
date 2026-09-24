# -*- coding: utf-8 -*-
"""云端收盘刷新（⑤ 自动更新迁移云端 · Phase 1：只写 gh-pages，不写 main）
=====================================================================
用法：python .github/cloud/cloud_refresh.py --mode probe|chain

- probe：不跑本地链，只做「部署目录组装 + 门禁」，用于验证云端管道本身（首次干跑用）。
- chain：先按**云端子集**跑 daily_refresh.py，再组装部署。
         子集 = 本地全链 − 本机专有步骤：
           --skip-deploy    发布交给 peaceiris（本机 _deploy_fundline_0911.py 写死 D:/ 路径）
           --skip-fullguard 全量补数 1-2h，超云端预算
           --skip-a5        A5 三步（扫描/看板数据/复盘）；2026-09-24 起已放开（A5 实验副本入库 backtest/a5_experiment）
           --no-main-push   Phase 1 约定：云端不写 main
           --skip-gushi     依赖本机 Chrome 自动化 profile，云端 Phase 1 不接管

门禁（任一不过即拒发，不写线上；对应 rc 2/3）：
  G1 结构：清单文件齐 + dual_system.html 的运行期 <script src> 全在清单内（防静默发旧文件）
  G2 新鲜度：enhanced_data.js / short_signals.js 的 as_of == 今日（北京时区）；
            chain 模式不满足 → status=no-new-data（绿，等价「非交易日/无新数据」）
  G3 防回归：线上同名文件 as_of 若**新于**本地 → 该文件不进发布集（保留线上更新版）

退出码：0 成功（含 no-new-data）/ 1 链失败 / 2 口径结构不合格（拒发）/ 3 外部端点不可用
输出：$GITHUB_OUTPUT 的 publish / status / live_url（供 workflow 的 if 与回读用）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STAGING = REPO / "_cloud_dist"
LIVE_BASE = "https://hawchou1995.github.io/quant-weight-system/"
RUN_ID = os.environ.get("GITHUB_RUN_ID", "local")
SHA = os.environ.get("GITHUB_SHA", "")

# ---- 发布清单（真值源 = _deploy_fundline_0911.py 的 SYNC；两处改动必须同步）----
SYNC = [
    "short_v3_fund_slip20_summary.json",
    "short_v3_fund_summary.json",
    "changelog.md",
    "changelog.html",
    "review_log.html",
    "kxmm_data.js",
    "echarts.min.js",
    "short_signals.js",
    "enhanced_data.js",
    "a5_pool.js",
    "market_breadth.js",
    "market_weather.js",
]
# 看板 HTML：dual_system.html 为准，index.html 由本脚本复制（与本地部署同口径）
HTML = "dual_system.html"

# 新鲜度锚点：文件内 "as_of": "YYYY-MM-DD"
AS_OF_RE = re.compile(r'"as_of"\s*:\s*"(\d{4}-\d{2}-\d{2})"')
# G2 硬门只看这两个（看板标题「数据截至 X」与命中一览都读它们）
G2_FILES = ("enhanced_data.js", "short_signals.js")

CHAIN_FLAGS = ["--skip-deploy", "--skip-fullguard",
               "--no-main-push", "--skip-gushi"]


def log(msg: str) -> None:
    print(msg, flush=True)


def line(t="-", n=78):
    log(t * n)


def md5(p: Path) -> str:
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def today_cn() -> str:
    """北京时区日期（GitHub runner 是 UTC，20:30 北京 = 12:30 UTC 同日，仍显式换算）"""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
    except Exception:
        return datetime.utcnow().strftime("%Y-%m-%d")


def as_of_of(text: str):
    m = AS_OF_RE.search(text)
    return m.group(1) if m else None


def live_text(name: str, timeout=30):
    """线上同名文件文本；不存在/网络失败 → None（不阻断）"""
    try:
        req = urllib.request.Request(LIVE_BASE + name,
                                     headers={"User-Agent": "Mozilla/5.0",
                                              "Cache-Control": "no-cache"})
        return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")
    except Exception as e:
        log(f"  ⚠ 线上读取 {name} 失败（跳过防回归比对）：{e}")
        return None


def ensure_win_path_shim() -> None:
    """Linux runner 路径兼容垫片（2026-09-24 加）。

    背景：链内 15 个脚本写死 Windows 绝对路径（D:/Documents/Workbuddy/股票基金/quant-weight-system，
    实测清单见 handoff）。POSIX 下该串不含前导 / 即为**相对路径**，而链内每一步都以仓库根为 cwd
    （daily_refresh.py 的 subprocess cwd=BASE，cloud_refresh 自身 cwd=REPO）→ 解析成 <repo>/D:/…
    → 必然找不到文件（实测 run 35938088628：市值快照 fetch_val_daily exit 1 → 中止后续步骤）。
    做法：在仓库根逐级建目录，末级软链回仓库自身 → 写死路径自动落到真文件。
    幂等；仅非 Windows 生效（Windows 不能建名为 "D:" 的目录，且本机原路径本就存在）。
    """
    if os.name == "nt":
        return
    link = REPO / "D:" / "Documents" / "Workbuddy" / "股票基金" / "quant-weight-system"
    try:
        if link.is_symlink() or link.exists():
            return
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(REPO, target_is_directory=True)
        log(f"[shim] 兼容软链已建：{link} → {REPO}")
    except Exception as e:
        log(f"  ⚠ 兼容软链创建失败（不阻断；写死 D:/ 路径的步骤可能仍失败）：{type(e).__name__}: {e}")


def run_chain(timeout: int) -> int:
    ensure_win_path_shim()
    cmd = [sys.executable, "daily_refresh.py"] + CHAIN_FLAGS
    env = os.environ.copy()
    # 云端专属 env（2026-09-24 加；本机链不经此处 → 本机行为一律不变）：
    #  A. REBASE_BUDGET_S：update_daily.py L401 的「复权基准漂移检测」相位预算（默认 2400s）。
    #     实测 run 35943548423：单步 40.4min 全烧在此（云端 17.3s/只 → 只处理 156/400；本机 4.5s/只
    #     同预算内能跑完）。云端压到 600s（≈34 只）省 ~35min；本机仍 2400s。
    #  B. FUND_NAV_WORKERS：fund_nav_update.py 并发（默认 8）。基金净值是链上第二大单点
    #     （3038 只 × 全历史下载），云端延迟高 → 提到 12（该脚本 docstring 的实测值）。
    #  C. FUND_NAV_BUDGET_S：同上基金净值步的硬时间预算（默认 0=不限）。实测 run 35943548423：
    #     该步 02:36:57 起 ≥29.2min 连一条 [200/N] 进度行都没有（云端完成 <200/3038 只，US
    #     runner 上 pingzhongdata 极慢）→ 无界等待=整链被拖死。压到 1800s：超预算即收工，已
    #     落盘的保留（每只独立整文件覆盖，幂等）、未跑的下一轮按「最陈旧优先」续补。
    #     本机不设此变量 → 全量刷，行为不变。
    # 三者都走 setdefault：workflow 若自己设了同名变量，以 workflow 为准。
    env.setdefault("REBASE_BUDGET_S", "600")
    env.setdefault("FUND_NAV_WORKERS", "12")
    env.setdefault("FUND_NAV_BUDGET_S", "1800")
    log(f"[chain] {' '.join(cmd)}  (timeout {timeout}s · REBASE_BUDGET_S={env['REBASE_BUDGET_S']}"
        f" · FUND_NAV_WORKERS={env['FUND_NAV_WORKERS']} · FUND_NAV_BUDGET_S={env['FUND_NAV_BUDGET_S']})")
    try:
        r = subprocess.run(cmd, cwd=str(REPO), timeout=timeout, env=env)
        return r.returncode
    except subprocess.TimeoutExpired:
        log(f"[chain] ⏱ 超时（{timeout}s）—— 视为失败")
        return 1


def runtime_deps() -> tuple[list, list]:
    """dual_system.html 的运行期本地 <script src> 及其未入清单者（G1 守卫）"""
    html = (REPO / HTML).read_text(encoding="utf-8", errors="replace")
    deps = list(dict.fromkeys(re.findall(r'<script src="([^":/]+\.js)"', html)))
    return deps, [d for d in deps if d not in SYNC]


def emit(**kw) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if not out:
        log("[outputs] " + json.dumps(kw, ensure_ascii=False))
        return
    with open(out, "a", encoding="utf-8") as f:
        for k, v in kw.items():
            f.write(f"{k}={v}\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["probe", "chain"], default="probe")
    ap.add_argument("--chain-timeout", type=int, default=7200,
                    help="链超时秒数（默认 7200=120min；job 上限 150min，留余量给门禁/组装）")
    ap.add_argument("--no-live-check", action="store_true", help="本地干跑时跳过线上比对")
    a = ap.parse_args()

    t0 = time.time()
    line("=")
    log(f"云端收盘刷新 · mode={a.mode} · run={RUN_ID} · sha={(SHA or 'n/a')[:8]} · 北京今日 {today_cn()}")
    line("=")

    # ---------- 0 环境探针 ----------
    df = REPO / "data_full"
    n_df = sum(1 for _ in df.glob("*.csv")) if df.is_dir() else 0
    log(f"[env] python {sys.version.split()[0]} · repo {REPO}")
    log(f"[env] data_full CSV {n_df} 个 · 部署清单 {len(SYNC)} 文件 · HTML {HTML}")

    # ---------- 1 链（chain 模式） ----------
    chain_rc = None
    if a.mode == "chain":
        if n_df == 0:
            log("[chain] ⛔ data_full 为空（缓存与种子均未就位）→ 拒绝跑链（rc 3）")
            emit(publish="false", status="no-data-cache", live_url=LIVE_BASE)
            return 3
        chain_rc = run_chain(a.chain_timeout)
        log(f"[chain] rc={chain_rc}")

    # ---------- 2 G1 结构门禁 ----------
    deps, deps_missing = runtime_deps()
    missing = [n for n in [HTML] + SYNC if not (REPO / n).exists()]
    if deps_missing or missing:
        log(f"❌ G1 结构门禁不过 —— 缺文件 {missing} · 依赖未入清单 {deps_missing}")
        emit(publish="false", status="structure-fail", live_url=LIVE_BASE)
        return 2
    log(f"✅ G1 结构门禁：{len(deps)} 个运行期 <script src> 全在清单内（{'、'.join(deps)}）")

    # ---------- 3 G3 防回归（线上更新的同名文件不覆盖） ----------
    skipped_newer = []
    for n in [HTML] + SYNC:
        p = REPO / n
        if a.no_live_check or p.suffix == ".html" or n in ("echarts.min.js",):
            continue
        lt = live_text(n)
        if lt is None:
            continue
        lo, live_o = as_of_of(p.read_text(encoding="utf-8", errors="replace")), as_of_of(lt)
        if lo and live_o and live_o > lo:
            skipped_newer.append(n)
            log(f"  ⏭ 防回归：线上 {n} as_of={live_o} 新于本地 {lo} —— 本次不发该文件")
    if skipped_newer:
        log(f"✅ G3 防回归：跳过 {len(skipped_newer)} 个文件（{'、'.join(skipped_newer)}）")

    # ---------- 4 G2 新鲜度门禁 ----------
    today = today_cn()
    as_ofs = {}
    for n in G2_FILES:
        as_ofs[n] = as_of_of((REPO / n).read_text(encoding="utf-8", errors="replace"))
    fresh = all(v == today for v in as_ofs.values())
    log(f"{'✅' if fresh else '⏳'} G2 新鲜度：{as_ofs} vs 今日 {today}")
    if a.mode == "chain" and not fresh:
        log("→ status=no-new-data（非交易日/数据未就绪）：不发布，退出 0")
        emit(publish="false", status="no-new-data", live_url=LIVE_BASE)
        return 0

    # ---------- 5 组装 staging ----------
    if STAGING.exists():
        shutil.rmtree(STAGING)
    STAGING.mkdir(parents=True)
    files = []
    for n in [HTML] + SYNC:
        if n in skipped_newer:
            continue
        dst = STAGING / n
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / n, dst)
        assert md5(dst) == md5(REPO / n), f"复制校验失败 {n}"
        files.append({"name": n, "md5": md5(dst)[:12], "bytes": dst.stat().st_size,
                      "as_of": as_of_of(dst.read_text(encoding="utf-8", errors="replace"))})
    shutil.copy2(REPO / HTML, STAGING / "index.html")
    assert md5(STAGING / HTML) == md5(STAGING / "index.html"), "index.html 双向同步失败"
    files.append({"name": "index.html", "md5": md5(STAGING / "index.html")[:12],
                  "bytes": (STAGING / "index.html").stat().st_size, "as_of": as_ofs.get(HTML)})

    manifest = {
        "run_id": RUN_ID, "sha": SHA, "mode": a.mode, "status": "published-candidate",
        "ts_cn": datetime.now().strftime("%Y-%m-%d %H:%M:%S") if not a.no_live_check else "n/a",
        "today_cn": today, "chain_rc": chain_rc, "g2_fresh": fresh,
        "runtime_deps": deps, "skipped_newer": skipped_newer, "files": files,
    }
    (STAGING / "_cloud_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    line("=")
    log(f"✅ staging 就绪：{STAGING} · {len(files)} 文件 · {sum(f['bytes'] for f in files)/1024:.0f} KB · 耗时 {time.time()-t0:.0f}s")
    for f in files:
        log(f"   {f['name']:42s} {f['md5']}  as_of={f.get('as_of')}")
    line("=")
    emit(publish="true", status="ok", live_url=LIVE_BASE, files=len(files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
