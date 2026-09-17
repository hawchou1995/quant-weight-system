# -*- coding: utf-8 -*-
"""HS300 指数行维护 + 交易日闸门（R-gate-0917）

背景：daily_refresh 旧闸门以「index_000300.csv 末行==今天」判交易日，但该文件长期
      无写手（全靠人工"补 HS300 指数行"，见 09-16 提交说明）→ 15:30 时末行必为昨天
      → 自动链恒打印 [skip] 非交易日，实际全靠傍晚人工 --force 追跑。

本脚本（链内步骤，位于数据步之后）：
  - 从数据源取**今日** HS300 日线（主：东财 kline；备：新浪 hq 快照，二者对 09-16 行逐位对拍过）
  - 取到 → 写入 / 就地刷新 index_000300.csv 末行（幂等：盘中写的非终值，收盘后重跑自动刷新），exit 0
  - 取不到（节假日 / 数据源未就绪）→ exit 3（约定码：调用方据此判"非交易日"，跳过后续步骤）

口径（与库内 09-15/09-16 行一致）：列序 date,open,high,low,close,volume；
  volume 单位 = 股（东财/新浪原始值 = 手，×100）；价格 2 位小数去尾零。
用法：
  python backtest/ensure_index_row.py             # 维护（写）
  python backtest/ensure_index_row.py --check     # 只查不写（验证闸门用）
  python backtest/ensure_index_row.py --file X    # 指定文件（测试用）
"""
import argparse
import json
import sys
import urllib.request
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DEFAULT_CSV = BASE / "index_000300.csv"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
EXIT_NOT_TRADING = 3            # 约定码：今日行情不可得（非交易日/未就绪）

EM_URL = ("https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.000300"
          "&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57"
          "&klt=101&fqt=0&end=20500101&lmt=8")


def _get(url, headers=None, enc="utf-8", timeout=15):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with op.open(req, timeout=timeout) as r:
        return r.read().decode(enc, errors="replace")


def fetch_em_bar(day):
    """东财日线：date==day 则返回 {date,open,high,low,close,vol_hand}，否则 None"""
    d = json.loads(_get(EM_URL))
    for k in (d.get("data") or {}).get("klines", []):
        f = k.split(",")
        # f51=date f52=open f53=close f54=high f55=low f56=volume(手) f57=amount
        if f[0] == day:
            return {"date": f[0], "open": float(f[1]), "close": float(f[2]),
                    "high": float(f[3]), "low": float(f[4]), "vol_hand": float(f[5])}
    return None


def fetch_sina_bar(day):
    """新浪快照（收缩后=当日终值）：仅当快照日期==day 时返回"""
    t = _get("https://hq.sinajs.cn/list=sh000300",
             {"Referer": "https://finance.sina.com.cn"}, enc="gbk")
    body = t.split('"')[1] if '"' in t else ""
    f = body.split(",")
    if len(f) < 32 or f[30] != day:
        return None
    return {"date": f[30], "open": float(f[1]), "high": float(f[4]), "low": float(f[5]),
            "close": float(f[3]), "vol_hand": float(f[8])}


def _fmt(v):
    s = f"{float(v):.2f}".rstrip("0").rstrip(".")
    return s or "0"


def make_row(bar):
    return (f'{bar["date"]},{_fmt(bar["open"])},{_fmt(bar["high"])},'
            f'{_fmt(bar["low"])},{_fmt(bar["close"])},{int(round(bar["vol_hand"] * 100))}')


def _row_equal(a, b):
    """按数值比较两行（价格容差 1e-6，量取整比较）"""
    try:
        fa, fb = a.split(","), b.split(",")
        if fa[0] != fb[0]:
            return False
        for i in (1, 2, 3, 4):
            if abs(float(fa[i]) - float(fb[i])) > 1e-6:
                return False
        return int(round(float(fa[5]))) == int(round(float(fb[5])))
    except Exception:                                    # noqa: BLE001
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只查不写")
    ap.add_argument("--file", default=str(DEFAULT_CSV), help="目标 csv（测试用）")
    args = ap.parse_args()

    csv = Path(args.file)
    if not csv.exists():
        print(f"[ensure] 缺文件 {csv}", flush=True)
        sys.exit(1)
    target = date.today().isoformat()

    raw = csv.read_bytes()
    # ⚠ 必须从**字节**判行尾：read_text 的 universal-newlines 会把 CRLF 统一成 LF，
    #   若据此回写会把整个文件的行尾改写（R-gate-0917 首跑踩过：2847 行伪 diff）。
    nl = b"\r\n" if b"\r\n" in raw else b"\n"
    lines = raw.decode("utf-8").splitlines()
    last_date = lines[-1].split(",")[0]

    bar, src = None, ""
    for name, fn in (("em", fetch_em_bar), ("sina", fetch_sina_bar)):
        try:
            bar = fn(target)
        except Exception as e:                           # noqa: BLE001
            print(f"[ensure] {name} 取数异常：{type(e).__name__}: {str(e)[:90]}", flush=True)
            bar = None
        if bar:
            src = name
            break
    if not bar:
        print(f"[ensure] 今日（{target}）HS300 行情不可得 → 非交易日（或数据源未就绪）；文件末行={last_date}",
              flush=True)
        sys.exit(EXIT_NOT_TRADING)

    row = make_row(bar)
    if last_date == target:
        if _row_equal(lines[-1], row):
            print(f"[ensure] {target} 行已最新（源={src}）：{lines[-1]}", flush=True)
            sys.exit(0)
        if args.check:
            print(f"[ensure][check] {target} 行可刷新：{lines[-1]} → {row}（源={src}）", flush=True)
            sys.exit(0)
        lines[-1] = row
        action = "refreshed"
    elif last_date < target:
        if args.check:
            print(f"[ensure][check] 可追加 {target} 行：{row}（源={src}；末行 {last_date}）", flush=True)
            sys.exit(0)
        lines.append(row)
        action = "appended"
    else:
        print(f"[ensure] 文件末行 {last_date} 晚于今日 {target}（异常）——不写入", flush=True)
        sys.exit(EXIT_NOT_TRADING)

    csv.write_bytes(nl.join(ln.encode("utf-8") for ln in lines) + nl)
    print(f"[ensure] {action} {target}: {row}（源={src}，volume 单位=股）", flush=True)
    sys.exit(0)


if __name__ == "__main__":
    main()
