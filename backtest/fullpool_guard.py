# -*- coding: utf-8 -*-
"""全量池守卫（2026-09-17 建，R-fullpool-0917）：确保三个系统吃到全市场最新数据
逻辑：① 跑新鲜度检查 → ② 陈旧 > STALE_GATE(100) 时自动执行 update_daily.py --all（禁代理环境）
      → ③ 复查并打印结论。陈旧 = 降级源只补了池内子集（如 440/7539）。
链内挂载：daily_refresh 数据更新步之后（[软]步；--skip-fullguard 跳过）。
用法：python backtest/fullpool_guard.py [--check-only]
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
BASE = HERE.parent
PY = sys.executable
STALE_GATE = 100
NO_PROXY_ENV = {**os.environ, "HTTP_PROXY": "", "HTTPS_PROXY": "", "http_proxy": "", "https_proxy": "",
                "NO_PROXY": "*", "no_proxy": "*"}


def _gate_n(f):
    """门控计数（2026-09-17 修）：可交易标的中真正陈旧的数量。
    旧口径把 1626 只 ETF（源滞后）+ 330 只退市股算成"陈旧"，分母失真是全量池守卫 ABORT 的真因。"""
    return int(f.get("stale_tradable", f.get("stale", 0)))


def freshness():
    r = subprocess.run([PY, str(HERE / "check_data_freshness.py")], cwd=str(BASE),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    print((r.stdout or "").strip(), flush=True)
    try:
        return json.loads((HERE / "_data_freshness.json").read_text(encoding="utf-8"))
    except Exception:
        return None


def main():
    t0 = time.time()
    check_only = "--check-only" in sys.argv
    f = freshness()
    if not f:
        print("[guard] 新鲜度检查失败——放弃守卫（软步骤）", flush=True)
        return
    n = _gate_n(f)
    if n <= STALE_GATE:
        print(f"[guard] 可交易陈旧 {n} ≤ {STALE_GATE}（A股 {f.get('stock_fresh','?')}/{f.get('stock_total','?')}）："
              f"全量池新鲜，无需补数（{time.time()-t0:.0f}s）", flush=True)
        return
    if check_only:
        print(f"[guard] 可交易陈旧 {n} > {STALE_GATE}：需全量补数（--check-only 模式未执行）", flush=True)
        return
    print(f"[guard] ⚠️ 可交易陈旧 {n} > {STALE_GATE}（降级源只补了池内子集）"
          f"→ 触发全量补数 update_daily.py --all（约 1-2h）", flush=True)
    r = subprocess.run([PY, str(BASE / "update_daily.py"), "--all"], cwd=str(BASE), env=NO_PROXY_ENV)
    print(f"[guard] update_daily --all 退出码 {r.returncode}（{time.time()-t0:.0f}s）", flush=True)
    f2 = freshness()
    if f2:
        n2 = _gate_n(f2)
        ok = n2 <= STALE_GATE
        print(f"[guard] 补数后复查：可交易陈旧 {n2} / A股 {f2.get('stock_fresh','?')}/{f2.get('stock_total','?')}"
              f" → {'✓ 全量池已对齐' if ok else '✗ 仍有陈旧（源侧限制，明日重试）'}（总 {time.time()-t0:.0f}s）", flush=True)
    # 落盘守卫记录（供看板/排查）
    (HERE / "_fullpool_guard_log.jsonl").open("a", encoding="utf-8").write(
        json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M"), "before": f, "after": f2}, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
