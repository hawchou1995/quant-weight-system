# -*- coding: utf-8 -*-
"""吸收后的集成验收（不联网）：
  T1 语法/导入
  T2 scan_lag manifest 路径 == 全量扫描路径（逐只一致）
  T3 merge_save → _IDX_PENDING 入队 → _flush_index 批量回写生效
  T4 _update_one 重试逻辑（构造必失败 fetcher，验证重试 3 次后入 fails）
"""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path("D:/Documents/Workbuddy/股票基金/quant-weight-system")))
import importlib
import data_index as DI
import update_daily as U
importlib.reload(U)

ok_all = True
print("=" * 68, flush=True)
print("T1 语法/导入", flush=True)
print(f"  update_daily 导入 OK，DI 挂载 = {U.DI is DI}", flush=True)
print(f"  UPD_RETRIES = {U.UPD_RETRIES}", flush=True)

print("=" * 68, flush=True)
print("T2 scan_lag 双路径一致性", flush=True)
TARGET = "2026-09-20"
a = U.scan_lag(TARGET, use_index=True)
b = U.scan_lag(TARGET, use_index=False)
sa, sb = {x[0] for x in a}, {x[0] for x in b}
da = {x[0]: x[3] for x in a}
db = {x[0]: x[3] for x in b}
mis = [k for k in (sa & sb) if da[k] != db[k]]
t2 = (sa == sb) and not mis
print(f"  manifest {len(sa)} 只 / 全量 {len(sb)} 只 / 尾日期差 {len(mis)} → {'PASS' if t2 else 'FAIL'}", flush=True)
ok_all &= t2

print("=" * 68, flush=True)
print("T3 merge_save → manifest 批量回写", flush=True)
import pandas as pd
fake = pd.DataFrame({"date": ["2026-09-10"], "open": [10.0], "high": [10.5],
                     "low": [9.8], "close": [10.2], "volume": [1000], "amount": [1e6]})
# 用真实存在的票但只在 manifest 上验证（先备份该文件）
src = U.OUT_DIR / "sh600000.csv"
bak = U.OUT_DIR / "_sh600000.csv.bak_absorb"
import shutil
shutil.copy(src, bak)
try:
    n0 = len(U._IDX_PENDING)
    U.merge_save("sh600000", fake, "")
    n1 = len(U._IDX_PENDING)
    print(f"  入队数 {n0} → {n1}（期望 +1）", flush=True)
    U._flush_index()
    n2 = len(U._IDX_PENDING)
    idx = DI.load_index(allow_stale=True)
    rec = idx.get("sh600000")
    print(f"  回写后 manifest[sh600000] = {rec}", flush=True)
    print(f"  队列已清空 = {n2 == 0}", flush=True)
    t3 = (n1 == n0 + 1) and n2 == 0 and rec is not None and rec[0] == "2026-09-10"
finally:
    shutil.copy(bak, src)          # 恢复原文件
    bak.unlink(missing_ok=True)
    DI.build_index(verbose=False)  # 重建 manifest 恢复到真实状态
print(f"  → {'PASS' if t3 else 'FAIL'}", flush=True)
ok_all &= t3

print("=" * 68, flush=True)
print("T4 重试退避逻辑（_update_one 是 main() 内闭包 → 提取源码独立执行）", flush=True)
import inspect, re as _re, textwrap
src_ud = Path(U.__file__).read_text(encoding="utf-8")
m = _re.search(r"    def _update_one\(item\):.*?\n        return \(sym, None, last_err\)\n", src_ud, _re.S)
assert m, "未能从 update_daily.py 提取 _update_one 源码"
fn_src = textwrap.dedent(m.group(0))

calls = {"n": 0}
class _Boom:
    @staticmethod
    def fetch_sina_etf(sym, retries=3):
        calls["n"] += 1
        raise RuntimeError("simulated source down")
    @staticmethod
    def _backoff(attempt, base=1.5, cap=8.0):
        pass                      # 测试中跳过真实 sleep
    @staticmethod
    def save_csv(*a, **k):
        pass
    @staticmethod
    def fetch_sina_daily(sym, retries=3):
        calls["n"] += 1
        raise RuntimeError("simulated source down")

ns = {"F": _Boom, "UPD_RETRIES": U.UPD_RETRIES, "merge_save": lambda *a, **k: None,
      "source": "sina", "src_fetch": _Boom.fetch_sina_daily}
exec(compile(fn_src, "<update_one>", "exec"), ns)
t0 = time.time()
sym, last, err = ns["_update_one"](("sh600000", "", "", ""))
el = time.time() - t0
print(f"  sym={sym} last={last} err={err} 调用次数={calls['n']} 耗时={el:.2f}s", flush=True)
t4 = calls["n"] >= U.UPD_RETRIES and err is not None and sym == "sh600000"
print(f"  → {'PASS' if t4 else 'FAIL'}（期望调用≥{U.UPD_RETRIES}次且返回 err）", flush=True)
ok_all &= t4

print("=" * 68, flush=True)
print(f"总结论：{'✅ 全部 PASS' if ok_all else '❌ 存在 FAIL'}", flush=True)
