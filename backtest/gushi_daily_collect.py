# -*- coding: utf-8 -*-
"""gushi.in 每日采集器（A 方案·自愈版）：零手动操作
流程：算出「最近 N 个交易日中缺失的日期」→ 选定 CDP 通道（自动化 profile 优先，其次用户已登录浏览器）
     → 一次页面会话批量取回这些日期 × 9 策略 + 12 共振因子 → 落盘 gushi_data/daily/<date>.json
     → 追加 picks_daily.jsonl → 打印摘要
自愈语义：浏览器没开、非交易日、会话掉线导致的空洞，下次运行自动补齐（只补缺失日，不重复写 jsonl）。
通道策略：
  9223 = 专用自动化 profile（D:/Tools/chrome-auto-profile）——离线时可自行拉起（独立窗口，绝不动用户浏览器）
  9222 = 用户本人的 Chrome（真实 profile 经 junction 开放调试端口）——只借用，永不拉起/重启
用法：python gushi_daily_collect.py                  # 自动：补齐最近 5 个交易日的空缺
     python gushi_daily_collect.py --days 20         # 回补窗口放大到 20 个交易日
     python gushi_daily_collect.py --date 2026-09-11  # 只采指定日期（强制重采）
     python gushi_daily_collect.py --no-launch      # CDP 离线时只跳过，不拉起浏览器
     python gushi_daily_collect.py --dry-run        # 只取数不落盘
"""
import argparse
import asyncio
import json
import subprocess
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

import websockets

CHROME = r"C:\Users\Admin\AppData\Local\Google\Chrome\Application\chrome.exe"
AUTO_PROFILE = r"D:\Tools\chrome-auto-profile"      # 专用自动化 profile（自己登录、自己跑）
AUTO_PORT = "9223"
USER_PORT = "9222"                                  # 用户真实浏览器（junction 绕 Chrome152 封锁）
HERE = Path(__file__).resolve().parent
OUT = HERE / "gushi_data"
DAILY = OUT / "daily"
DAILY.mkdir(parents=True, exist_ok=True)

FACTORS = {"1": "竞价多头", "2": "盘前强势", "3": "晨星量化", "4": "竞价阿尔法", "5": "早盘之星",
           "9": "T+1闪电", "11": "黄金两点半", "ten31": "十点半", "bigcap": "大市值"}
RESON = ["baofactor13", "fengkou", "fivestar", "gnbid", "highscore", "hottopic",
         "linkgene", "momentum", "researchhot", "sectorlead", "testplate", "vip"]
TARGET_URL = "https://i.gushi.in/factor.html"


def counts(day):
    """某日数据的 (策略条数, 共振条数)"""
    n_f = sum(len((day.get(f"f_{f}", {}).get("result") or {}).get("stock_list") or []) for f in FACTORS)
    n_r = sum(len((day.get(f"r_{r}", {}).get("result") or {}).get("stock_list") or []) for r in RESON)
    return n_f, n_r


def missing_days(n):
    """最近 n 个交易日里尚未采到（各存放目录都没有非空数据）的日期；日历未含今天时，工作日也补上今天。
    站点服务端硬限「最近 15 天」（VIP 同），其 earliest_date 缓存在 gushi_data/window.json —— 窗口外日期不再重试。"""
    csv = HERE.parent / "index_000300.csv"
    ds = []
    if csv.exists():
        ds = [l.split(",")[0] for l in csv.read_text(encoding="utf-8").strip().splitlines()[1:]]
    ds = ds[-n:]
    today = date.today().strftime("%Y-%m-%d")
    if today not in ds and date.today().weekday() < 5:
        ds.append(today)
    floor = site_window_floor()
    todo = []
    for d in sorted(set(ds)):
        if floor and d < floor:
            continue
        got = 0
        for p in (DAILY / f"{d}.json", OUT / "raw_vip" / f"{d}.json", OUT / "raw" / f"{d}.json"):
            if p.exists():
                try:
                    got += sum(counts(json.loads(p.read_text(encoding="utf-8"))))
                except Exception:
                    pass
        if got == 0:
            todo.append(d)
    return todo


def site_window_floor():
    """站点可查窗口起点（服务端 403 响应里的 earliest_date），无缓存则 None"""
    p = OUT / "window.json"
    if p.exists():
        try:
            return (json.loads(p.read_text(encoding="utf-8")) or {}).get("earliest_date")
        except Exception:
            return None
    return None


def save_window_floor(data, todo):
    """从本次 403 响应里抽取窗口起点并缓存（窗口随时推移，每次都能自纠）"""
    for d in todo:
        r = (data.get(d) or {}).get("f_1") or {}
        if r.get("code") == 403:
            sh = (r.get("result") or {}).get("strategy_history") or {}
            if sh.get("earliest_date"):
                (OUT / "window.json").write_text(json.dumps(
                    {"earliest_date": sh["earliest_date"], "latest_date": sh.get("latest_date"),
                     "checked": date.today().strftime("%Y-%m-%d")}, ensure_ascii=False), encoding="utf-8")
                print(f"[窗口] 站点可查起点 {sh['earliest_date']}（更早的日期不再重试）")
                return


def cdp_alive(port):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=3).read()
        return True
    except Exception:
        return False


def boot_auto_profile():
    """拉起我们自己的自动化 profile（独立窗口，绝不动用户正在用的浏览器）"""
    subprocess.Popen([CHROME, f"--user-data-dir={AUTO_PROFILE}", f"--remote-debugging-port={AUTO_PORT}",
                      "--no-first-run", "--no-default-browser-check", TARGET_URL], close_fds=True)
    for _ in range(30):
        time.sleep(1)
        if cdp_alive(AUTO_PORT):
            return True
    return False


def close_auto_profile():
    """优雅关闭本次由脚本拉起的自动化窗口（不留残窗）"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{AUTO_PORT}/json/version", timeout=5) as r:
            ws_url = json.load(r)["webSocketDebuggerUrl"]

        async def _close():
            async with websockets.connect(ws_url, open_timeout=8) as ws:
                await ws.send(json.dumps({"id": 1, "method": "Browser.close"}))
                try:
                    await asyncio.wait_for(ws.recv(), timeout=5)
                except Exception:
                    pass
        asyncio.run(_close())
        print("[cleanup] 已关闭本次拉起的自动化窗口")
    except Exception as e:
        print(f"[cleanup] 关闭失败（可忽略）：{e}")


def candidate_ports(no_launch):
    """可用通道列表（按优先级）：自动化 profile → 用户浏览器（只借用）→ 拉起自动化 profile"""
    ports = []
    if cdp_alive(AUTO_PORT):
        ports.append((AUTO_PORT, "自动化 profile"))
    if cdp_alive(USER_PORT):
        ports.append((USER_PORT, "用户浏览器（只借用，不重启）"))
    if ports:
        return ports, False
    if no_launch:
        print("[SKIP] 两个 CDP 通道都离线且 --no-launch：未拉起浏览器")
        sys.exit(0)
    print("[boot] 拉起自动化 Chrome（独立 profile + 调试端口）…")
    if boot_auto_profile():
        return [(AUTO_PORT, "自动化 profile（本次拉起）")], True
    print("[FAIL] 拉起失败——若自动化窗口已在运行（无调试端口），请先关掉它再重试")
    sys.exit(1)


def page_ws(port):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=8) as r:
        ts = json.load(r)
    pages = [t for t in ts if t.get("type") == "page" and "i.gushi.in" in (t.get("url") or "")]
    if pages:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json/activate/{pages[0]['id']}", timeout=5).read()
        except Exception:
            pass
        return pages[0]["webSocketDebuggerUrl"]
    # 没有 gushi 页则新建（Chrome 111+ 要求 PUT，GET 会 405）
    req = urllib.request.Request(f"http://127.0.0.1:{port}/json/new?{TARGET_URL}", method="PUT")
    with urllib.request.urlopen(req, timeout=8) as r:
        t = json.load(r)
    time.sleep(3)
    return t["webSocketDebuggerUrl"]


async def navigate(ws_url, url):
    async with websockets.connect(ws_url, max_size=64 * 1024 * 1024, open_timeout=10) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Page.navigate", "params": {"url": url}}))
        await ws.recv()


async def wait_clear(ws_url, tries=15):
    for _ in range(tries):
        try:
            state = json.loads(await ev(ws_url, "JSON.stringify({t: document.title, cf: !!document.querySelector('#challenge-form, .cf-turnstile, [name=cf-turnstile-response]')})"))
            if not state.get("cf") and "请稍候" not in (state.get("t") or ""):
                return True
        except Exception:
            pass
        await asyncio.sleep(3)
    return False


async def ev(ws_url, js):
    async with websockets.connect(ws_url, max_size=256 * 1024 * 1024, open_timeout=10) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                                  "params": {"expression": js, "returnByValue": True, "awaitPromise": True}}))
        while True:
            m = json.loads(await ws.recv())
            if m.get("id") == 1:
                if "exceptionDetails" in m.get("result", {}):
                    raise RuntimeError(json.dumps(m["result"]["exceptionDetails"], ensure_ascii=False)[:300])
                return m["result"]["result"].get("value")


async def collect_dates(ws_url, dates):
    """一个页面会话里把多个交易日的数据一次取回（含 me）"""
    js = ("(async () => { const out = {}; "
          f"for (const d of {json.dumps(dates)}) {{ const day = {{}}; "
          f"for (const f of {json.dumps(list(FACTORS))}) day['f_' + f] = await (await fetch('/api.php?action=factor-stocks&factor_id=' + f + '&date=' + d, {{credentials:'same-origin'}})).json(); "
          "day['reson'] = await (await fetch('/api.php?action=resonance-factors&date=' + d, {credentials:'same-origin'})).json(); "
          f"for (const r of {json.dumps(RESON)}) day['r_' + r] = await (await fetch('/api.php?action=resonance-stocks&factor_ids=' + r + '&date=' + d, {{credentials:'same-origin'}})).json(); "
          "out[d] = day; } "
          "out['me'] = await (await fetch('/api.php?action=me', {credentials:'same-origin'})).json(); "
          "return JSON.stringify(out); })()")
    return json.loads(await ev(ws_url, js))


def day_lines(trade_date, day):
    """把某日原始数据摊平成 picks_daily.jsonl 的行"""
    lines = []
    for f, nm in FACTORS.items():
        for s in ((day.get(f"f_{f}", {}).get("result") or {}).get("stock_list") or []):
            lines.append({"date": trade_date, "kind": "factor", "strategy": nm, "fid": f, **{k: s.get(k) for k in (
                "stock_code", "stock_name", "price", "open_rise", "change_rate", "entity_rate",
                "market_value", "total_score", "factor_count")},
                "tags": [t.get("factor_name") for t in (s.get("factor_tags") or [])],
                "concepts": (s.get("block_names") or [])[:8]})
    for r in RESON:
        for s in ((day.get(f"r_{r}", {}).get("result") or {}).get("stock_list") or []):
            lines.append({"date": trade_date, "kind": "resonance", "strategy": r, "fid": r, **{k: s.get(k) for k in (
                "stock_code", "stock_name", "price", "open_rise", "change_rate", "entity_rate",
                "market_value", "total_score")},
                "concepts": (s.get("block_names") or [])[:8]})
    return lines


def run_channels(ports, todo, dry_run):
    """按顺序尝试通道；取到数据即落盘并返回 ((port, chan), role, total, 'ok')；
    全部失败返回 (None, role, 0, reason)：'window'=待采日期全在站点窗口外，'nodata'=其它（多为登录失效）"""
    role, reason = None, "nodata"
    for port, chan in ports:
        print(f"[通道] 试 CDP {port} · {chan}")
        try:
            ws_url = page_ws(port)
            asyncio.run(navigate(ws_url, TARGET_URL))
            print(f"[cf] 挑战通过={asyncio.run(wait_clear(ws_url))}")
            data = asyncio.run(collect_dates(ws_url, todo))
        except Exception as e:
            print(f"[warn] 通道 {port} 异常，跳过：{str(e)[:120]}")
            continue
        role = (data.get("me", {}).get("result") or {}).get("role")
        save_window_floor(data, todo)
        if sum(sum(counts(data.get(d) or {})) for d in todo) == 0:
            codes = [((data.get(d) or {}).get("f_1") or {}).get("code") for d in todo]
            if codes and all(c == 403 for c in codes):
                print(f"[info] 通道 {port} role={role}：{len(todo)} 个待采日期全在站点可查窗口之外（403）")
                reason = "window"
                continue
            print(f"[warn] 通道 {port} role={role} 未取到数据，换下一通道")
            continue
        total = 0
        fh = None if dry_run else open(OUT / "picks_daily.jsonl", "a", encoding="utf-8")
        for d in todo:
            day = data.get(d) or {}
            n_f, n_r = counts(day)
            if n_f + n_r == 0:  # 取不到数据就不落盘：日期保持「缺失」，下次运行自动重试
                print(f"  {d} | 无数据，保留为待补")
                continue
            if fh:
                (DAILY / f"{d}.json").write_text(json.dumps(day, ensure_ascii=False), encoding="utf-8")
                for x in day_lines(d, day):
                    fh.write(json.dumps(x, ensure_ascii=False) + "\n")
            total += n_f + n_r
            print(f"  {d} | factor {n_f} 条 / resonance {n_r} 条")
        if fh:
            fh.close()
        return (port, chan), role, total, "ok"
    return None, role, 0, reason


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-launch", action="store_true")
    ap.add_argument("--date", default=None, help="只采指定日期 YYYY-MM-DD（强制重采）")
    ap.add_argument("--days", type=int, default=5, help="自愈回补窗口：最近 N 个交易日")
    ap.add_argument("--dry-run", action="store_true", help="只取数不落盘（验证登录态/接口）")
    ap.add_argument("--keep-open", action="store_true", help="采集完不关闭自动化窗口（默认关掉，不留残窗）")
    a = ap.parse_args()

    todo = [a.date] if a.date else missing_days(a.days)
    if not todo:
        print(f"[gushi-daily] 最近 {a.days} 个交易日数据齐全，无需采集")
        sys.exit(0)

    ports, launched = candidate_ports(a.no_launch)
    print(f"[todo] 待采日期 {len(todo)} 个：{', '.join(todo)}")
    used, role, total, reason = run_channels(ports, todo, a.dry_run)
    if not used and not launched and not a.no_launch and all(p != AUTO_PORT for p, _ in ports):
        print("[boot] 在线通道均未取到数据，拉起自动化 profile 再试…")
        if boot_auto_profile():
            launched = True
            used, role, total, reason = run_channels([(AUTO_PORT, "自动化 profile（本次拉起）")], todo, a.dry_run)

    mode = "（dry-run 不落盘）" if a.dry_run else ""
    if used:
        print(f"[gushi-daily] 通道 {used[0]}（{used[1]}）| role={role} | 增采 {total} 条{mode}")
    elif reason == "window":
        print(f"[gushi-daily] 待采日期全在站点窗口外（站点硬限：仅最近 15 天）| role={role} | 窗口内数据齐全，无需补采{mode}")
    else:
        print(f"[gushi-daily] 全部通道未取到数据（最后 role={role}）")
        print("[WARN] 登录态异常——请在自动化窗口（profile D:/Tools/chrome-auto-profile）登录一次 gushi；"
              "登录态会持久保存，之后无需再操作")
    if launched and not a.keep_open:
        close_auto_profile()


if __name__ == "__main__":
    main()
