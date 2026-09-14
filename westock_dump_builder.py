# -*- coding: utf-8 -*-
"""westock CLI → dump JSON 构建器（把 fetch_close_westock.py 的人工前置自动化）
====================================================================
原人工流程（文档 §2.7）：agent 用 westock MCP data_kline 拉数 → 手工整理 dump JSON。
本脚本改为：直接调本机 westock CLI（无需 agent/MCP）→ 解析 markdown 表 → 生成 dump JSON。

用法：
    python westock_dump_builder.py --codes sh600301,sz000001 [--days 5] [--out westock_dump_<date>.json]
    python westock_dump_builder.py --lag-list data_lag_list.csv --limit 200   # 只取滞后清单前 N 只
    python fetch_close_westock.py --dump westock_dump_<date>.json            # 合并进 data_full

铁律（与 fetch_close_westock.py 一致，勿改）：
    行序 = [date, open, last, high, low, volume, amount]，last 是收盘价（不是 high）
    只写 > --since（默认库里最新日）的行，避免用不同源覆盖已对齐的历史
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent
WESTOCK = r"C:\Users\Admin\.local\bin\westock.exe"
COLS = ["date", "open", "last", "high", "low", "volume", "amount"]


def run_cli(codes, days):
    """调 westock CLI 拉日线（前复权），返回 stdout 文本"""
    cmd = [WESTOCK, "kline", ",".join(codes), "--period", "day", "--fq", "qfq", "--limit", str(days)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    if r.returncode != 0:
        raise RuntimeError(f"westock CLI 失败: {r.stderr[:200]}")
    return r.stdout


def parse_md(text, code_set):
    """解析 markdown 表 → {code: [[date, open, last, high, low, volume, amount], ...]}（保留 CLI 行序）"""
    out = {}
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 7 or cells[0] in ("date", "---") or set(cells[0]) <= {"-", " "}:
            continue
        code, d = cells[0], cells[1]
        if code not in code_set or not re.match(r"^\d{4}-\d{2}-\d{2}$", d):
            continue
        try:
            row = [d, float(cells[2]), float(cells[3]), float(cells[4]), float(cells[5]),
                   float(cells[6]), float(cells[7]) if len(cells) > 7 else 0.0]
        except (ValueError, IndexError):
            continue
        out.setdefault(code, []).append(row)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", default=None, help="逗号分隔代码")
    ap.add_argument("--lag-list", default=None, help="滞后清单 csv（取第 1 列 sym）")
    ap.add_argument("--limit", type=int, default=0, help="滞后清单取前 N 只")
    ap.add_argument("--days", type=int, default=5, help="每只拉多少根日线")
    ap.add_argument("--since", default=None, help="只保留该日期之后的行（默认=昨天，即只补最新交易日）")
    ap.add_argument("--batch", type=int, default=20, help="CLI 单次多码上限（保守 20）")
    ap.add_argument("--out", default=None, help="输出 dump JSON 路径")
    a = ap.parse_args()

    if a.codes:
        codes = [c.strip() for c in a.codes.split(",") if c.strip()]
    elif a.lag_list:
        codes = [ln.split(",")[0].strip() for ln in Path(a.lag_list).read_text(encoding="utf-8").splitlines() if ln.strip()]
        if a.limit:
            codes = codes[:a.limit]
    else:
        print(__doc__)
        sys.exit(1)

    since = a.since
    if since is None:
        # 逐只取本地末行日期，只补「比本地更新」的行（避免用不同源覆盖已对齐历史）
        pass  # 在下面按 code 现算

    out_path = Path(a.out) if a.out else BASE / f"westock_dump_{date.today().strftime('%Y%m%d')}.json"

    def local_last(c):
        f = BASE / "data_full" / f"{c}.csv"
        if not f.exists():
            return "9999-99-99"  # 本地无文件 → 不补（新标的走 fetch_full_universe）
        with open(f, "rb") as fh:
            fh.seek(max(0, fh.seek(0, 2) - 200))
            return fh.read().decode("utf-8", "replace").strip().splitlines()[-1].split(",")[0]

    all_rows, fail, skipped, halted = {}, [], [], []
    for i in range(0, len(codes), a.batch):
        chunk = codes[i:i + a.batch]
        try:
            rows = parse_md(run_cli(chunk, a.days), set(chunk))
        except Exception as e:
            print(f"[warn] 批次 {i // a.batch + 1} 失败：{str(e)[:120]}", flush=True)
            fail += chunk
            continue
        for c in chunk:
            floor = since if since else local_last(c)
            rs = [r for r in rows.get(c, []) if r[0] > floor]
            # ⚠ 停牌日陷阱（2026-09-14 实测 sh600301）：westock 对停牌日返回 open/high/low/volume/amount 全 0
            #   的占位行（仅 last=前收）。直接合并会写出「全零 K 线」，毒化 ATR/rolling-min/量比等指标 → 必须丢弃。
            good = [r for r in rs if not (r[1] == 0 and r[3] == 0 and r[4] == 0 and r[5] == 0)]
            if rs and not good:
                halted.append(c)
            elif good:
                all_rows[c] = good
            elif rows.get(c):
                skipped.append(c)   # CLI 有数据但无新行 → 本地已是最新
            else:
                fail.append(c)
        print(f"  [{min(i + a.batch, len(codes))}/{len(codes)}] 需补 {len(all_rows)} 只 / 已最新 {len(skipped)} 只"
              f" / 停牌跳过 {len(halted)} 只", flush=True)

    out_path.write_text(json.dumps(all_rows, ensure_ascii=False), encoding="utf-8")
    n_rows = sum(len(v) for v in all_rows.values())
    print(f"\n[dump] 需补 {len(all_rows)} 只 / {n_rows} 行 → {out_path}")
    if skipped:
        print(f"[已最新] {len(skipped)} 只（无需补）")
    if halted:
        print(f"[停牌] {len(halted)} 只（当日无成交，全零行已丢弃）：{halted[:8]}{' …' if len(halted) > 8 else ''}")
    if fail:
        print(f"[未取到] {len(fail)} 只：{fail[:8]}{' …' if len(fail) > 8 else ''}")
    if not all_rows:
        print("→ 无新行需合并，未生成有效 dump")
        return
    print(f"下一步：python fetch_close_westock.py --dump {out_path.name}")


if __name__ == "__main__":
    main()
