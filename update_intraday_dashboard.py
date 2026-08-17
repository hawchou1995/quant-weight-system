# -*- coding: utf-8 -*-
"""盘中增量更新：9:30/14:30 用当日盘中快照刷新 GitHub 体系看板数据
====================================================================
背景：线上看板（dual_system.html）数据来自 Quant data 全量库，收盘任务 15:30 才更新到
      当日。盘中（9:30/14:30）看板停留在上一交易日，用户要求盘中也能看到当日涨跌。

方案（不污染 Quant data，收盘任务天然覆盖恢复）：
1. 读取 行情监控/raw_kline/YYYY-MM-DD.json（盘中快照：watchlist 标的，60 根含当日盘中根）
2. patch enhanced_data.js：对快照内每只标的，更新 details[code].px / .chg（当日涨跌幅，
   基于昨收），meta 追加 intraday 标注；short_pool.js 同样 patch
3. 重跑 build_dual_system.py → dual_system.html 显示当日盘中行情
4. 15:30 收盘任务 refresh_daily.py 会用真实收盘数据全量重建 enhanced_data.js，
   盘中 patch 自动消失，无需回滚

注意：分数/档位保持收盘口径（盘中无法重算四因子：无 amount、无 200 根历史），
      看板 px/chg 显示盘中实时，score/tier 为上一交易日收盘口径，页面有标注。

用法：python update_intraday_dashboard.py [--snapshot 2026-08-17]
"""
import os, sys, json, re
from pathlib import Path

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
MONITOR = Path(r"D:/Documents/Workbuddy/股票基金/行情监控")
PY = sys.executable


def patch_js_file(path, snap_items, today, note_tag, snap_date):
    """把快照标的的 px/chg 写入 window.XXX 数据文件（保留其余结构）"""
    src = Path(path).read_text(encoding="utf-8")
    m = re.search(r"window\.(\w+) = (.*);\s*$", src, re.S)
    if not m:
        print(f"❌ 无法解析 {path}")
        return False
    var, body = m.group(1), m.group(2)
    data = json.loads(body)
    patched = 0
    for it in snap_items:
        code = it["code"]
        rows = it["rows"]
        if not rows or it.get("setcode") == "33":
            continue
        last = rows[-1]
        if last.get("d") != today:
            continue
        if len(rows) < 2:
            continue
        prev = rows[-2]
        px = last["c"]
        prev_c = prev["c"]
        chg = round((px / prev_c - 1) * 100, 2) if prev_c else None
        # 打 patch：enhanced_data.js 的 details 与 short_pool.js 的 details 结构一致
        for store in (data.get("details", {}),):
            if code in store:
                store[code]["px"] = px
                store[code]["chg"] = chg
                patched += 1
    if patched:
        if "meta" in data:
            data["meta"]["as_of"] = snap_date  # 带横线 YYYY-MM-DD，与收盘口径一致
            data["meta"]["intraday"] = f"{snap_date} 盘中行情（{note_tag}）· 分数为收盘口径"
        elif "as_of" in data:
            data["as_of"] = snap_date
            data["intraday_note"] = f"{snap_date} 盘中行情（{note_tag}）· 分数为收盘口径"
    Path(path).write_text(f"window.{var} = {json.dumps(data, ensure_ascii=False)};", encoding="utf-8")
    print(f"✅ {path}: patch {patched} 只标的 px/chg → 今日盘中")
    return patched > 0


def main():
    import argparse, subprocess, datetime
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default=datetime.date.today().strftime("%Y-%m-%d"))
    args = ap.parse_args()
    snap_file = MONITOR / "raw_kline" / f"{args.snapshot}.json"
    if not snap_file.exists():
        print(f"❌ 快照不存在: {snap_file}（先跑 monitor.py 体系早盘/尾盘快照）")
        sys.exit(1)
    snap = json.load(open(snap_file, encoding="utf-8"))
    today = snap["snapshot_date"].replace("-", "")
    snap_date = snap["snapshot_date"]
    print(f"盘中快照: {snap_date} | {len(snap['items'])} 标的")

    ok1 = patch_js_file(BASE / "enhanced_data.js", snap["items"], today, "实时", snap_date)
    ok2 = patch_js_file(BASE / "short_pool.js", snap["items"], today, "实时", snap_date)

    if not (ok1 or ok2):
        print("⚠️ 无标的可 patch（快照可能为空或全为场外基金），跳过重建")
        sys.exit(0)

    print("== 重建看板 build_dual_system.py ==")
    r = subprocess.run([PY, str(BASE / "build_dual_system.py")], capture_output=True, text=True)
    if r.stdout:
        print(r.stdout.strip().splitlines()[-2:])
    if r.returncode != 0:
        print(f"❌ build_dual_system 失败:\n{r.stderr[-1500:]}")
        sys.exit(1)
    print("✅ 盘中增量更新完成：看板 px/chg = 当日盘中，score/tier = 收盘口径")


if __name__ == "__main__":
    main()
