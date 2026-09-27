# -*- coding: utf-8 -*-
"""gen_trade_cal.py — 生成/刷新仓库内置交易日历 trade_cal_sina.csv（2026-09-27，R-cloud-cal-0927）

为什么需要：云端链的「下一交易日」推算是关键路径（决定买日/了结日）。原先只依赖
`ak.tool_trade_date_hist_sina()` 联网获取 —— 若云端该请求失败就会退化成「跳周末」近似，
遇到中秋/国庆这类跨节窗口会把买日算错（如 2026-09-24 → 09-25 实为休市，正确是 09-28）。

做法：把权威日历**内置进仓库**（含未来日期到当年年末），使云端/本机都能离线得到正确交易日；
`hpdk_candidates.next_trade_days` 的优先级 = 内置文件 → akshare → 跳周末近似。

⚠ 这是**数据维护**脚本，不是链步骤：每年年末前重跑一次即可（或由链在 akshare 可用时刷新）。
用法: python gen_trade_cal.py
"""
import pathlib
import sys

R = pathlib.Path(__file__).resolve().parent
OUT = R / "trade_cal_sina.csv"


def main():
    try:
        import akshare as ak
        t = ak.tool_trade_date_hist_sina()
        ds = sorted({str(x) for x in t["trade_date"].astype(str) if len(str(x)) >= 10})
    except Exception as e:
        print("!! akshare 取日历失败：%r —— 保留既有文件不覆盖" % (e,))
        return 2
    if len(ds) < 5000:
        print("!! 日历条目异常少（%d）—— 拒绝覆盖" % len(ds))
        return 2
    old = 0
    if OUT.exists():
        old = sum(1 for _ in OUT.read_text(encoding="utf-8-sig").splitlines()[1:] if _.strip())
    OUT.write_text("trade_date\n" + "\n".join(ds) + "\n", encoding="utf-8")
    print("已写 %s：%d 条（原 %d 条）· %s .. %s" % (OUT.name, len(ds), old, ds[0], ds[-1]))
    fut = [d for d in ds if d > "2026-09-24"][:5]
    print("2026-09-24 之后前 5 个交易日 =", fut)
    for d in ("2026-09-25", "2026-09-28"):
        print("  %s 交易日=%s" % (d, d in set(ds)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
