# -*- coding: utf-8 -*-
"""R-gushi-early-0917：gushi 采集改成「链首试采（不续费）+ 链尾正式采集（可续费）」双保险

现场（2026-09-17 夜实测）：
  · 链首执行测试真跑了一次采集，结果暴露两件事：
    ① `[todo] 待采日期 1 个：2026-09-18` → 采集器会主动去取「下一交易日」，站点返回 HTML 错误页
       （`Unexpected token '<', "<!DOCTYPE "`）→ 脚本把「全部通道失败」统一归因为
       **`[WARN] 登录态异常——请在自动化窗口登录一次 gushi`**。这是**误诊**：登录态好的很，
       真实原因是「当日数据尚未上线」。这条假告警每天都会刷，必须改文案。
    ② 站点当日数据**实测最早 16:22 才有**（2026-09-14 那次：trading_date=2026-09-14 /
       is_today=true / role=vip，mtime 16:22）。所以链首 15:31 采集**太早**，会失败。

设计（为什么不只留一处）：
  · VIP = 24h 卡，到期锚点 = 上次续费时刻（今天 17:38）。链尾正式采集落在 ~16:38 → 窗口内，
    到期日当天**无需续费即可采到**（「一天顶两天」的机制）。但链一旦慢（如 fullpool_guard
    触发 1-2h 全量补数）就会跨过到期点 → role 非 vip → 脚本拒绝落盘（保护数据集）→ 当日丢失。
  · 故：**链首**做一次「试采」（`--days 10`，**不带 --renew**，纯机会主义，永不扣分）；
    **链尾**保留正式采集（带 `--renew`，是唯一允许扣分的入口，受脚本 `_renewed_today()`
    每日 1 次上限 + 余额不足保护）。
  · 两次都写同一个 `daily/<date>.json`：脚本对 `role != vip` 一律拒绝落盘 → 不存在
    「后一次用脱敏数据覆盖前一次好数据」的风险。

用法：python _patch_gushi_dual_0917.py
"""
import sys
import py_compile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OK = True


def patch(rel, old, new, tag, count=1):
    global OK
    p = BASE / rel
    t = p.read_text(encoding="utf-8")
    if new in t:
        print(f"  [skip] {tag}（已打过）")
        return
    if t.count(old) != count:
        print(f"  [FAIL] {tag}：锚点命中 {t.count(old)} 次（期望 {count}）")
        OK = False
        return
    p.write_text(t.replace(old, new), encoding="utf-8")
    print(f"  [ok]   {tag}")


print("=" * 74)
print("P1 链首块：改为「试采」，不带 --renew，并修正注释")
print("=" * 74)
patch("daily_refresh.py",
      '''# ---- gushi 策略股池采集（R-gushi-early-0917：**移到链首**）----
# 为什么提前（用户 2026-09-17 拍板「明天早点跑 gushi」）：
#   ① 站点 VIP 是 24h 卡，到期锚点 = 上次续费时刻。原实现放链尾，全链跑到 ~16:38 才采集；
#      一旦上游慢（如 fullpool_guard 触发 1-2h 全量补数）就会跨过到期点 → role 非 vip → 脚本
#      拒绝落盘（保护数据集）→ 当日数据丢失。
#   ② 站点当日数据实测 16:22 已可用（2026-09-14：trading_date=2026-09-14 / is_today=true / role=vip），
#      链首 ~15:31 采集即安全窗口内 → 到期日当天无需续费也能采到（「一天顶两天」的机制就在这里）。
#   ③ 采集不依赖链内任何其他步骤，只读站点，前置无副作用。
# 非致命：CDP 离线 / 未登录 / 依赖缺失都不阻断主链。

''',
      '''# ---- gushi 策略股池采集（R-gushi-early-0917 双保险：链首试采 + 链尾正式采集）----
# 为什么放两处（2026-09-17 夜实测依据）：
#   ① 站点 VIP = 24h 卡，到期锚点 = 上次续费时刻。链尾正式采集落在 ~16:38 → 在窗口内，
#      到期日当天**无需续费也能采到**（「一天顶两天」的机制就在这里）。
#   ② 但链一旦慢（如 fullpool_guard 触发 1-2h 全量补数）就会跨过到期点 → role 非 vip →
#      脚本拒绝落盘（保护数据集）→ 当日数据丢失。故链首再做一次**机会主义试采**。
#   ③ 站点当日数据实测**最早 16:22** 才有（2026-09-14：trading_date=2026-09-14 / is_today=true /
#      role=vip，mtime 16:22）→ 链首 15:31 试采大概率「当日未上线」而空手，属预期，不影响正式采集。
#   ④ 链首试采**不带 --renew**（永不扣分）；唯一允许扣分的入口是链尾正式采集。
#   ⑤ 试采若拿到非 vip 数据也不会落盘（脚本对 role != vip 一律拒绝写）→ 不存在「坏数据覆盖好数据」。
# 非致命：CDP 离线 / 未登录 / 依赖缺失都不阻断主链。

''', "P1a 链首注释改双保险")

patch("daily_refresh.py",
      '''        print(f"\\n========== gushi 策略股池采集 collect_gushi ==========", flush=True)
        # --renew：非 VIP 时自动续费 1 天卡（30 论坛积分）后继续采集（用户 2026-09-16 授权；护栏见脚本注释）
        r = subprocess.run([gp, "backtest/gushi_daily_collect.py", "--days", "10", "--renew"],
                           cwd=str(BASE), capture_output=True, text=True, timeout=900)
        for ln in ((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-12:]:
            print(ln, flush=True)
    else:
        print("[skip] gushi 采集：无可用解释器（websockets 缺失）", flush=True)
''',
      '''        print(f"\\n========== gushi 策略股池采集 collect_gushi（链首·试采，不续费）==========", flush=True)
        r = subprocess.run([gp, "backtest/gushi_daily_collect.py", "--days", "10"],
                           cwd=str(BASE), capture_output=True, text=True, timeout=900)
        for ln in ((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-8:]:
            print(ln, flush=True)
    else:
        print("[skip] gushi 采集：无可用解释器（websockets 缺失）", flush=True)

# ---- gushi 正式采集（链尾·唯一允许续费的入口）----
# 位置依据：链首试采（~15:31）大概率早于站点当日数据上线时刻（实测最早 16:22）；
#           链尾实测落在 ~16:38，落在「数据已上线」且「VIP 未到期」的窗口内。
# 扣分护栏全部在采集脚本内：_renewed_today() 每日 1 次上限 + 余额不足不扣分 + 非 vip 不落盘。
if not fails:
    _gp2 = _gushi_py()
    if _gp2:
        print(f"\\n========== gushi 策略股池采集 collect_gushi（链尾·正式，可续费）==========", flush=True)
        # --renew：非 VIP 时自动续费 1 天卡（30 论坛积分）后继续采集（用户 2026-09-16 授权；护栏见脚本注释）
        r = subprocess.run([_gp2, "backtest/gushi_daily_collect.py", "--days", "10", "--renew"],
                           cwd=str(BASE), capture_output=True, text=True, timeout=900)
        for ln in ((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-12:]:
            print(ln, flush=True)
''', "P1b 拆成链首试采 + 链尾正式")

print()
print("=" * 74)
print("P2 采集脚本：修正「登录态异常」误诊文案（真实原因多为当日数据未上线/日期越界）")
print("=" * 74)
patch("backtest/gushi_daily_collect.py",
      '''        print("[WARN] 登录态异常——请在自动化窗口（profile D:/Tools/chrome-auto-profile）登录一次 gushi；登录态会持久保存，之后无需再操作")''',
      '''        # ⚠ 2026-09-17 修：原文案一律归因「登录态异常」是**误诊**（实测链首试采 15:31 时
        #   站点当日数据尚未上线 → 返回 HTML 错误页 → 全通道失败，与登录无关）。
        #   改为分场景提示，避免每天刷假告警、把真问题淹没。
        _is_future = any(str(x) >= time.strftime("%Y-%m-%d") for x in (todo or []) if x)
        print("[WARN] 全部通道未取到数据——先查是不是**当日数据尚未上线**："
              "站点当日数据实测最早 16:22 可用（2026-09-14 实测），收盘后 ~16:20 之前采集必然空手，属正常；"
              "待采日期含未来交易日（如次日）时也会返回 HTML 错误页。"
              "若已过 16:30 且仍是本提示，才是登录态问题："
              "请在自动化窗口（profile D:/Tools/chrome-auto-profile）登录一次 gushi；登录态会持久保存，之后无需再操作")''',
      "P2 误诊文案修正")

print()
print("=" * 74)
print("编译校验")
print("=" * 74)
for rel in ("daily_refresh.py", "backtest/gushi_daily_collect.py"):
    try:
        py_compile.compile(str(BASE / rel), doraise=True)
        print(f"  [ok] {rel}")
    except Exception as e:
        OK = False
        print(f"  [FAIL] {rel}: {type(e).__name__}: {e}")

print()
print("总结论：" + ("✅ 全部落地" if OK else "❌ 存在 FAIL"))
sys.exit(0 if OK else 1)