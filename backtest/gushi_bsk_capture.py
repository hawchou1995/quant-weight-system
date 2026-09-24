# -*- coding: utf-8 -*-
"""gushi 采集的 bsk 兜底通道：借「用户已登录的 Chrome」取当日因子/共振数据。

为什么需要它（2026-09-24 实测）：
  * 站点 /api.php?action=resonance-factors|resonance-stocks **只支持最新交易日**
    （旧日期返回 409「因子共振仅支持最新交易日」）→ 共振数据错过当天即永久缺失；
  * 专用自动化 profile（CDP 9223，D:/Tools/chrome-auto-profile）会话会失效（实测 API 返回 HTML）；
    用户 Chrome 也经常没有 9222 调试端口 → 采集器可能出现「全通道未取到数据」；
  * 本脚本用 browser-skill（bsk）驱动用户真实 Chrome（VIP 会话）直接取数，
    产物格式与 backtest/gushi_daily_collect.py 完全一致（daily/<date>.json + picks_daily.jsonl 行）。

用法：
  python backtest/gushi_bsk_capture.py                        # 采当日（16:20 前拒绝，防半成品）
  python backtest/gushi_bsk_capture.py --only-if-missing      # 兜底模式：当日已有策略+共振就跳过
  python backtest/gushi_bsk_capture.py --date 2026-09-23 --out-dir <dir> --no-jsonl   # 沙盒验证
退出码：0 成功/跳过 · 3 bsk 不可用 · 4 未取到数据
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gushi_daily_collect as G  # noqa: E402  import 安全：主流程在 __main__ 保护下

BSK = r"C:\Users\Admin\.local\bin\bsk.exe"
EARLY_GUARD = "16:20"          # 站点当日数据实测最早 ~16:22 上线
MARK_A, MARK_B = "@@JSON@@", "@@END@@"
CHUNK = 8                      # 每次 evaluate 取住的端点数（避免单次载荷过大）


def bsk(args, timeout=180):
    env = dict(os.environ)
    env["BSK_AUTO_START"] = "0"
    r = subprocess.run([BSK] + args, capture_output=True, env=env, timeout=timeout)
    out = (r.stdout or b"").decode("utf-8", "replace")
    err = (r.stderr or b"").decode("utf-8", "replace")
    return r.returncode, out, err


def js_chunk(keys):
    """keys: [(outkey, url), ...]；返回带标记的取数 JS。"""
    lines = ["(async () => { const out = {};",
             " const J = async (k, p) => { try { const r = await fetch(p, {credentials:'same-origin'});",
             "  const t = await r.text(); let v; try { v = JSON.parse(t); }",
             "  catch (e) { v = {code: r.status, msg: 'non-json', snippet: t.slice(0, 160)}; } out[k] = v; }",
             "  catch (e) { out[k] = {code: -1, msg: String(e).slice(0, 160)}; } };"]
    for k, url in keys:
        lines.append(" await J(%s, %s);" % (json.dumps(k), json.dumps(url)))
    lines.append(" return %s + JSON.stringify(out) + %s; })()" % (json.dumps(MARK_A), json.dumps(MARK_B)))
    return " ".join(lines)


def eval_chunk(sid, keys):
    rc, out, err = bsk(["evaluate", "--session", sid, js_chunk(keys)])
    if rc != 0:
        raise RuntimeError("bsk evaluate rc=%d err=%s" % (rc, err.strip()[:200]))
    i, j = out.find(MARK_A), out.rfind(MARK_B)
    if i < 0 or j < 0:
        raise RuntimeError("evaluate 输出缺少标记：%s" % out.strip()[:200])
    return json.loads(out[i + len(MARK_A):j])


def endpoint_keys(d):
    keys = [("me", "/api.php?action=me"),
            ("reson", "/api.php?action=resonance-factors&date=" + d)]
    for f in G.FACTORS:
        keys.append(("f_" + f, "/api.php?action=factor-stocks&factor_id=%s&date=%s" % (f, d)))
    for r in G.RESON:
        keys.append(("r_" + r, "/api.php?action=resonance-stocks&factor_ids=%s&date=%s" % (r, d)))
    return keys


def summarize(day):
    rows = []
    for f, nm in G.FACTORS.items():
        rows.append(("策略 " + nm, len((day.get("f_" + f, {}).get("result") or {}).get("stock_list") or [])))
    for r in G.RESON:
        rows.append(("共振 " + r, len((day.get("r_" + r, {}).get("result") or {}).get("stock_list") or [])))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="采集日期 YYYY-MM-DD（默认今日）")
    ap.add_argument("--out-dir", default=None, help="输出目录（默认 backtest/gushi_data）")
    ap.add_argument("--jsonl", default=None, help="jsonl 路径（默认 <out-dir>/picks_daily.jsonl）")
    ap.add_argument("--no-jsonl", action="store_true", help="不追加 jsonl（沙盒验证用）")
    ap.add_argument("--only-if-missing", action="store_true", help="当日已有策略+共振则跳过")
    ap.add_argument("--allow-early", action="store_true", help="允许 16:20 前采当日（可能半成品）")
    ap.add_argument("--force", action="store_true", help="新数据少于现有也覆盖")
    ap.add_argument("--keep-tab", action="store_true", help="采完不停会话")
    a = ap.parse_args()

    d = a.date or date.today().strftime("%Y-%m-%d")
    today = date.today().strftime("%Y-%m-%d")
    out_dir = Path(a.out_dir) if a.out_dir else G.OUT
    daily = out_dir / "daily"
    daily.mkdir(parents=True, exist_ok=True)
    jsonl = Path(a.jsonl) if a.jsonl else (out_dir / "picks_daily.jsonl")
    dst = daily / ("%s.json" % d)

    if d == today and not a.allow_early and datetime.now().strftime("%H:%M") < EARLY_GUARD:
        print("[skip] 现在 %s < %s（站点当日数据最早 ~16:22 上线）→ 拒绝采当日，防半成品（--allow-early 强制）"
              % (datetime.now().strftime("%H:%M"), EARLY_GUARD))
        return 0

    if a.only_if_missing and dst.exists():
        try:
            nf0, nr0 = G.counts(json.loads(dst.read_text(encoding="utf-8")))
            if nf0 > 0 and nr0 > 0:
                print("[skip] %s 已在库（策略 %d / 共振 %d）→ 无需兜底" % (d, nf0, nr0))
                return 0
        except Exception as e:
            print("[warn] 现有 %s 解析失败：%s（继续采集）" % (dst.name, e))

    rc, out, err = bsk(["session", "start", "--json"])
    if rc != 0:
        print("[ERR] bsk session start 失败（daemon/浏览器不可用）：%s" % (err.strip()[:200] or out.strip()[:200]))
        return 3
    try:
        t = out.strip()
        sid = json.loads(t[t.find("{"):t.rfind("}") + 1])["session_id"]
    except Exception:
        print("[ERR] 无法解析 bsk session 输出：%s" % out.strip()[:200])
        return 3
    print("[bsk] session=%s" % sid)

    rc, out, err = bsk(["tab", "create", "--url", G.TARGET_URL, "--session", sid])
    if rc != 0:
        print("[ERR] 打开 gushi 页面失败：%s" % (err.strip()[:200] or out.strip()[:200]))
        bsk(["session", "stop", sid])
        return 3
    time.sleep(6)

    day, keys = {}, endpoint_keys(d)
    for i in range(0, len(keys), CHUNK):
        part = keys[i:i + CHUNK]
        try:
            day.update(eval_chunk(sid, part))
        except Exception as e:
            print("[ERR] 取数失败（第 %d 批 %s）：%s" % (i // CHUNK + 1, [k for k, _ in part], str(e)[:200]))
            if not a.keep_tab:
                bsk(["session", "stop", sid])
            return 4
        print("[bsk] 第 %d 批完成：%s" % (i // CHUNK + 1, ", ".join(k for k, _ in part)))

    if not a.keep_tab:
        bsk(["session", "stop", sid])

    role = (day.get("me", {}).get("result") or {}).get("role")
    nf, nr = G.counts(day)
    print("[取数] role=%s  策略条数=%d  共振条数=%d" % (role, nf, nr))
    for nm, n in summarize(day):
        if n == 0:
            print("   · %s = 0" % nm)
    if role != "vip":
        print("[WARN] role=%s（非 VIP）——站点脱敏数据不落盘（保护数据集）" % role)
        return 4
    if nf + nr == 0:
        print("[WARN] 未取到任何数据（当日数据可能尚未上线）→ 不落盘，等下次运行")
        return 4

    if dst.exists() and not a.force:
        try:
            nf0, nr0 = G.counts(json.loads(dst.read_text(encoding="utf-8")))
            if nf + nr < nf0 + nr0:
                print("[WARN] 新数据(%d)少于现有(%d) → 不覆盖（--force 强制）" % (nf + nr, nf0 + nr0))
                return 0
        except Exception:
            pass

    dst.write_text(json.dumps(day, ensure_ascii=False), encoding="utf-8")
    print("[落盘] %s  %d B" % (dst, dst.stat().st_size))

    if not a.no_jsonl:
        rows = G.day_lines(d, day)
        with jsonl.open("a", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        print("[jsonl] 追加 %d 行 → %s（去重交给 gushi_data_guard.py --dedupe）" % (len(rows), jsonl))

    if nr == 0:
        if d == today:
            print("[WARN] 当日共振为 0 —— 若早于 %s 稍后重跑可再试（共振仅最新交易日可得）" % EARLY_GUARD)
        else:
            print("[info] 非最新交易日：共振接口只支持最新日（预期 409），仅策略可回补")
    return 0


if __name__ == "__main__":
    sys.exit(main())