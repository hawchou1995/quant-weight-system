# -*- coding: utf-8 -*-
"""gushi.in 采集器 · bsk 通道（借「用户已登录的浏览器」，零手动登录、零凭据提取）

为什么存在
----------
生产采集器 `gushi_daily_collect.py` 走 CDP：要么用我们自己的自动化 profile（需登录），
要么连用户 9222（Chrome 136+ 默认 profile 已封锁）。bsk（browser-skill）扩展活在用户
**已登录的 Default profile** 里，因此 09-15 之后的第三条通道 = **借扩展的 session 在页面内 fetch**。

设计要点
--------
* **schema 单一真值源**：直接 `import gushi_daily_collect`，复用 FACTORS / RESON / counts /
  day_lines / missing_days / save_window_floor / DAILY —— 产出与生产采集器逐字节同构。
* **不碰凭据**：只读 `/api.php?action=me` 的 `role` 字段；不打印 username / csrf_token / cookie。
* **只有 role == "vip" 才落盘**（沿用生产语义：非 VIP 一律脱敏，拒绝污染数据集）。
* **按块取数**：单次 evaluate 内含 22 个端点的老做法会超 RPC 超时；改为分块（10 / 6 / 6），
  块失败自动降级为逐端点重取。每块 `--timeout 3m`。
* **幂等落盘**：写 `daily/<date>.json`；`picks_daily.jsonl` 先按 date 剔除旧行（备份后重写）
  再追加，重复运行不产生脏行。

用法
----
  python backtest/gushi_bsk_collect.py --date 2026-09-24 --dry-run
  python backtest/gushi_bsk_collect.py --date 2026-09-24
  python backtest/gushi_bsk_collect.py                 # 自动补最近 5 个交易日缺口
  python backtest/gushi_bsk_collect.py --ensure-session # 无 session 时自动建/收尾

rc: 0 成功 / 2 非 VIP（拒绝落盘）/ 3 浏览器或 session 不可用 / 4 未取到任何数据
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import gushi_daily_collect as GC  # noqa: E402  复用生产采集器的常量与摊平逻辑

BSK = os.environ.get("BSK_BIN", r"C:\Users\Admin\.local\bin\bsk.exe")
TARGET_URL = GC.TARGET_URL
OUT = GC.OUT
DAILY = GC.DAILY
LOG = OUT / "collect_bsk_last.log"

# 分块：快端点一组，共振端点两组（resonance-stocks 单请求可达 25s+）
CHUNKS = [
    [("f_%s" % f, "/api.php?action=factor-stocks&factor_id=%s&date=%s" % (f, "%(d)s")) for f in GC.FACTORS]
    + [("reson", "/api.php?action=resonance-factors&date=%(d)s")],
    [("r_%s" % r, "/api.php?action=resonance-stocks&factor_ids=%s&date=%%(d)s" % r) for r in GC.RESON[:6]],
    [("r_%s" % r, "/api.php?action=resonance-stocks&factor_ids=%s&date=%%(d)s" % r) for r in GC.RESON[6:]],
]


def log(msg: str) -> None:
    print(msg, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


# ------------------------------------------------------------------ bsk 调用
def bsk(args, proc_timeout=260):
    env = dict(os.environ)
    env["BSK_AUTO_START"] = "0"
    p = subprocess.run([BSK] + args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env, timeout=proc_timeout)
    return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()


def ev(session, js, rpc_timeout="3m", proc_timeout=270):
    """跑一段 JS，返回 (value, err)。走 --json 拿机器可读的 {"ok":true,"value":…}"""
    rc, out, err = bsk(["evaluate", "--session", session, "--json",
                        "--timeout", rpc_timeout, js], proc_timeout)
    if rc != 0:
        return None, "cli-rc=%s %s" % (rc, (err or out).replace("\n", " ")[:180])
    try:
        j = json.loads(out)
    except Exception:
        return None, "cli-nonjson:" + out[:160]
    if not j.get("ok"):
        return None, "rpc-not-ok:" + json.dumps(j, ensure_ascii=False)[:160]
    return j.get("value"), None


JS_FETCH_MANY = (
    "(async()=>{const out={};const eps=%(eps)s;"
    "for(const kv of eps){const k=kv[0],u=kv[1];"
    "try{const r=await fetch(u,{credentials:'same-origin'});const t=await r.text();"
    "try{out[k]={ok:true,code:r.status,body:JSON.parse(t)};}"
    "catch(e){out[k]={ok:false,code:r.status,head:t.slice(0,120)};}}"
    "catch(e){out[k]={ok:false,code:-1,head:String(e).slice(0,160)};}}"
    "return out;})()"
)


def fetch_many(session, eps, rpc_timeout="3m"):
    """一次 evaluate 取多个端点；返回 {key: payload|None} 与错误信息"""
    js = JS_FETCH_MANY % {"eps": json.dumps(eps, ensure_ascii=False)}
    v, err = ev(session, js, rpc_timeout=rpc_timeout)
    if err:
        return None, err
    if not isinstance(v, dict):
        return None, "bad-value-type:" + type(v).__name__
    res, bad = {}, []
    for k, _u in eps:
        item = v.get(k) or {}
        if item.get("ok"):
            res[k] = item.get("body")
        else:
            res[k] = None
            bad.append("%s(http=%s)" % (k, item.get("code")))
    return res, ("; ".join(bad[:4]) if bad else None)


def fetch_date(session, d):
    """取某交易日的全部 22 个端点（分块 + 失败降级逐端点）"""
    day, problems = {}, []
    for ci, chunk in enumerate(CHUNKS):
        eps = [(k, u % {"d": d}) for k, u in chunk]
        res, err = fetch_many(session, eps)
        if res is None:
            log("  [块%d] 整块失败（%s）→ 逐端点重取" % (ci, err))
            res = {}
            for k, u in eps:
                one, e1 = fetch_many(session, [(k, u)])
                if one is None:
                    problems.append("%s:%s" % (k, e1))
                    res[k] = None
                else:
                    res[k] = one.get(k)
                    if one.get(k) is None:
                        problems.append("%s:null" % k)
        for k, _u in eps:
            body = res.get(k)
            if body is None:
                day[k] = {"code": None, "result": None}   # counts() 计 0
            else:
                day[k] = body
    return day, problems


# ------------------------------------------------------------------ session
def ensure_session(requested, allow_create):
    """返回 (session_id, created_here)。requested 为空且 allow_create 时自动建一个。"""
    if requested:
        return requested, False
    rc, out, err = bsk(["browsers", "--json"])
    if rc != 0:
        log("[session] browsers 失败：%s" % (err or out)[:160])
        return None, False
    try:
        insts = json.loads(out)
    except Exception:
        return None, False
    if not insts:
        log("[session] 没有已连接的浏览器 —— 请确认 browser-skill 扩展处于「已启用」且 daemon 在跑")
        return None, False
    bid = insts[0].get("instance_id")
    rc, out, err = bsk(["session", "start", "--browser", str(bid), "--json"])
    if rc != 0:
        log("[session] start 失败：%s" % (err or out)[:160])
        return None, False
    try:
        sid = json.loads(out).get("session_id")
    except Exception:
        sid = None
    log("[session] 自动建立 session=%s（browser=%s）" % (sid, bid))
    return sid, True


def goto_and_wait(session, tries=8, sleep_s=3.0):
    """导航到 factor.html 并轮询 /api.php?action=me 直到返回 JSON（取代只看标题的 wait_clear）"""
    rc, out, err = bsk(["navigate", "--session", session, TARGET_URL], 90)
    if rc != 0:
        log("[nav] 失败：%s" % (err or out)[:160])
    for i in range(tries):
        v, e = ev(session, "(async()=>{try{const r=await fetch('/api.php?action=me',{credentials:'same-origin'});"
                          "const t=await r.text();try{const j=JSON.parse(t);"
                          "return {state:'json',role:(j.result||{}).role};}catch(x){"
                          "return {state:'not-json:'+t.length};}}catch(x){return {state:'err'};}})()",
                  rpc_timeout="40s")
        if e:
            log("[me] 第%d次探测错误：%s" % (i + 1, e))
        elif isinstance(v, dict) and v.get("state") == "json":
            log("[me] 第%d次探测 = JSON, role=%s" % (i + 1, v.get("role")))
            return v.get("role")
        else:
            log("[me] 第%d次探测 = %s" % (i + 1, (v or {}).get("state")))
        time.sleep(sleep_s)
    return None


# ------------------------------------------------------------------ 落盘
def append_idempotent(dates_done, dry_run):
    """把 daily/<d>.json 里已落盘的数据摊平进 picks_daily.jsonl：先剔同 date 旧行（备份）再追加"""
    p = OUT / "picks_daily.jsonl"
    old = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    keep, dropped = [], 0
    for ln in old:
        if not ln.strip():
            continue
        try:
            if json.loads(ln).get("date") in dates_done:
                dropped += 1
                continue
        except Exception:
            pass
        keep.append(ln)
    new = []
    for d in dates_done:
        day = json.loads((DAILY / ("%s.json" % d)).read_text(encoding="utf-8"))
        new += [json.dumps(x, ensure_ascii=False) for x in GC.day_lines(d, day)]
    if dry_run:
        log("[dry] 将删 %d 行 / 增 %d 行（picks_daily.jsonl）" % (dropped, len(new)))
        return dropped, len(new)
    if p.exists():
        bak = p.with_name(p.name + ".bak-bskappend-" + time.strftime("%Y%m%d_%H%M%S"))
        bak.write_bytes(p.read_bytes())
    p.write_text("\n".join(keep + new) + "\n", encoding="utf-8")
    log("[盘] picks_daily.jsonl：剔同日期旧行 %d，追加 %d 行" % (dropped, len(new)))
    return dropped, len(new)


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", action="append", default=[], help="交易日 YYYY-MM-DD，可多次")
    ap.add_argument("--days", type=int, default=5, help="不带 --date 时补最近 N 个交易日缺口")
    ap.add_argument("--session", default="", help="复用已有 bsk session（缺省则自动建）")
    ap.add_argument("--ensure-session", action="store_true", help="无 session 时自动建（用完收尾）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-guard", action="store_true", help="跳过 gushi_data_guard.py")
    args = ap.parse_args()

    session = args.session
    created = False
    if not session and args.ensure_session:
        session, created = ensure_session("", True)
    if not session:
        rc, out, _e = bsk(["session", "list"])
        if out:
            for ln in out.splitlines()[1:]:
                f = ln.split()
                if f:
                    session = f[0]
                    log("[session] 复用现有 session=%s" % session)
                    break
    if not session:
        log("[err] 没有可用 session（加 --ensure-session 可自动建）")
        return 3

    try:
        role = goto_and_wait(session)
        dates = sorted(set(args.date)) or GC.missing_days(args.days)
        if args.date:
            log("[目标] 指定日期：%s" % ", ".join(dates))
        else:
            log("[目标] 最近 %d 个交易日缺口：%s" % (args.days, ", ".join(dates) or "无"))
        if role is None and not dates:
            log("[err] 页面不可用（me 探测未得 JSON）且无待采日期")
            return 3

        def role_now():
            v, _e = ev(session, "(async()=>{try{const r=await fetch('/api.php?action=me',{credentials:'same-origin'});"
                                "const j=JSON.parse(await r.text());return (j.result||{}).role;}catch(x){return null;}})()",
                       rpc_timeout="40s")
            return v if isinstance(v, str) else None

        if role not in ("vip",):
            r2 = role_now()
            log("[warn] role=%s（非 vip）—— 拒绝落盘以保护数据集" % r2)
            return 2

        todo = [d for d in dates if args.date or True]
        done, days, total = [], {}, 0
        for d in todo:
            t0 = time.time()
            day, probs = fetch_date(session, d)
            n_f, n_r = GC.counts(day)
            log("  %s | factor %d 条 / resonance %d 条 | %.1fs%s"
                % (d, n_f, n_r, time.time() - t0,
                   ("  ⚠ " + "; ".join(probs[:3])) if probs else ""))
            if n_f + n_r == 0:
                log("  %s | 无数据，保留为待补" % d)
                continue
            if not args.dry_run:
                (DAILY / ("%s.json" % d)).write_text(json.dumps(day, ensure_ascii=False), encoding="utf-8")
            else:
                log("  [dry] 将写 daily/%s.json" % d)
            days[d] = day
            done.append(d)
            total += n_f + n_r

        if not done:
            log("[err] 未取到任何数据（rc=4）")
            return 4
        GC.save_window_floor(days, done)
        append_idempotent(done, args.dry_run)

        if not args.no_guard and not args.dry_run:
            g = HERE / "gushi_data_guard.py"
            if g.exists():
                p = subprocess.run([sys.executable, "-X", "utf8", str(g), "--days", "5"],
                                   capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(HERE))
                tail = [l for l in (p.stdout or "").splitlines() if l.strip()][-8:]
                log("[guard] rc=%s" % p.returncode)
                for l in tail:
                    log("  " + l)
        log("[done] 落盘 %d 个交易日 / %d 条 | role=vip" % (len(done), total))
        return 0
    finally:
        if created:
            bsk(["session", "stop", session], 60)
            log("[session] 收尾：已停止自动建立的 session %s" % session)


if __name__ == "__main__":
    sys.exit(main())
