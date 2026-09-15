# -*- coding: utf-8 -*-
"""
新浪日线快速拉取（2026-09-08 并行化提速）
============================================
背景：akshare stock_zh_a_daily 每次调用都新建 py_mini_racer JS VM 解码 klc_kl.js
（实测 HTTP 0.1s / 全流程 1.79s，JS 解码是瓶颈）→ 8 线程也只有 ~1 只/s。

本模块：每线程复用 MiniRacer 上下文（eval hk_js_decode 一次），直连新浪两个接口：
  1. klc_kl.js  → 原始行情（JS 加密，d() 解码）
  2. qfq.js     → 前复权因子（纯 JS 对象，eval 即可）
  qfq 价 = 原始价 / 因子（与 akshare 口径一致，volume 单位=股）
用法：from fast_sina_fetch import fetch_fast; df = fetch_fast("sh600000")
"""
import threading
import time
import requests
import pandas as pd

from py_mini_racer import MiniRacer
from akshare.stock.stock_zh_a_sina import hk_js_decode

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
HIST_URL = "https://finance.sina.com.cn/realstock/company/{}/hisdata_klc2/klc_kl.js"
QFQ_URL = "https://finance.sina.com.cn/realstock/company/{}/qfq.js"
HEADERS = ["date", "open", "high", "low", "close", "volume", "amount"]

_tls = threading.local()


def _ctx():
    ctx = getattr(_tls, "ctx", None)
    if ctx is None:
        ctx = MiniRacer()
        ctx.eval(hk_js_decode)
        _tls.ctx = ctx
    return ctx


def fetch_fast(sym: str, retries: int = 3):
    """直连新浪拉前复权日线（2016-01-01 起），失败返回 None"""
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(HIST_URL.format(sym), timeout=10, headers=UA)
            if r.status_code != 200 or len(r.text) < 200:
                time.sleep(0.3 * attempt)
                continue
            encoded = r.text.split("=")[1].split(";")[0].replace('"', "")
            dict_list = _ctx().call("d", encoded)
            raw = pd.DataFrame(dict_list)
            # ⚠ 2026-09-15 修复：新浪 klc_kl.js 的日期带 "Z"（UTC-aware），与 qfq.js 的朴素日期
            #   merge 时抛 `Cannot join tz-naive with tz-aware DatetimeIndex` → 被本函数裸 except 吞掉
            #   → 整条「直连通道」对所有标的静默返回 None（一直如此，此前未暴露）。
            #   统一为 tz-naive（UTC 零点即北京时间同日，取日期不歧义）。
            raw.index = pd.DatetimeIndex(pd.to_datetime(raw["date"], errors="coerce", utc=True)).tz_localize(None)
            del raw["date"]
            raw = raw[~raw.index.isna()]

            r2 = requests.get(QFQ_URL.format(sym), timeout=10, headers=UA)
            if r2.status_code != 200 or len(r2.text) < 50:
                time.sleep(0.3 * attempt)
                continue
            fac = pd.DataFrame(eval(r2.text.split("=")[1].split("\n")[0])["data"])
            fac.columns = ["date", "qfq_factor"]
            fac.index = pd.DatetimeIndex(pd.to_datetime(fac.date))
            del fac["date"]

            temp = pd.merge(raw, fac, left_index=True, right_index=True, how="outer")
            # ⚠ 2026-09-15 修复：原来对**整表** ffill+dropna → 解码数据里未使用的 postVol/postAmt
            #   多为空，dropna 会把 95% 的真实行情行一起删掉（实测茅台 6005 行 → 仅剩 52 行，静默截断）。
            #   正确做法：只对因子列前向填充 + 只按行情列判缺失。
            temp["qfq_factor"] = temp["qfq_factor"].ffill()
            temp = temp[temp["close"].notna()]
            temp = temp.astype(float).dropna(subset=["open", "high", "low", "close", "volume", "amount"])
            temp = temp.drop_duplicates(subset=["open", "high", "low", "close", "volume", "amount"])
            for col in ("open", "high", "low", "close"):
                temp[col] = (temp[col] / temp["qfq_factor"]).round(2)
            temp = temp.iloc[:, :-1]
            temp = temp[temp.index >= "2016-01-01"]
            out = temp.reset_index()
            out["date"] = out["date"].dt.strftime("%Y-%m-%d")
            return out[HEADERS]
        except Exception as e:
            if attempt == retries:
                print(f"[fast_sina_fetch] {sym} 取数失败（{type(e).__name__}: {str(e)[:80]}）", flush=True)
            time.sleep(0.3 * attempt)
    return None


if __name__ == "__main__":
    import sys
    sym = sys.argv[1] if len(sys.argv) > 1 else "sh600000"
    t0 = time.time()
    df = fetch_fast(sym)
    print(f"{sym}: {len(df)} 行, 最后 {df['date'].iloc[-1]}, 耗时 {time.time()-t0:.2f}s")
