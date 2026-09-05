import sys
sys.path.insert(0, r"D:\Documents\Workbuddy\股票基金\quant-weight-system")
import update_daily as U
try:
    import fetch_full_universe as F
    print("F._backoff:", hasattr(F, "_backoff"))
    print("F.fetch_sina_daily:", hasattr(F, "fetch_sina_daily"))
except Exception as e:
    print("F import err:", e)
fixed = U.run_rebase_check("2026-09-05", "sina")
print("REBASE_FIXED_COUNT:", fixed)
