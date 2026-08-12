# -*- coding: utf-8 -*-
"""v1.4 仓位模型参数扫描对比：增量步进(STEP 10-30%) vs 目标制+上限(CAP 10-50%) vs v1.2 基线
双池：19 关注池 + 39 只×19 领域池。输出 position_model_compare.json + 控制台汇总"""
import sys, json
sys.path.insert(0, ".")
import pandas as pd
import weight_system_backtest as wsb
from weight_system_backtest import load_data, compute_summary

# 39 只验证池（与 validate_industry_v2.py 保持一致）
TMP_UNIVERSE = [
    ("600519", "贵州茅台", "白酒"), ("000858", "五粮液", "白酒"), ("600887", "伊利股份", "消费"),
    ("603288", "海天味业", "消费"), ("600036", "招商银行", "银行"), ("601398", "工商银行", "银行"),
    ("300750", "宁德时代", "新能源"), ("601012", "隆基绿能", "光伏"), ("300274", "阳光电源", "新能源"),
    ("600438", "通威股份", "光伏"), ("600276", "恒瑞医药", "医药"), ("603259", "药明康德", "医药"),
    ("300760", "迈瑞医疗", "医药"), ("000333", "美的集团", "家电"), ("000651", "格力电器", "家电"),
    ("601088", "中国神华", "煤炭"), ("601225", "陕西煤业", "煤炭"), ("601318", "中国平安", "保险"),
    ("601601", "中国太保", "保险"), ("600900", "长江电力", "公用"), ("600905", "三峡能源", "公用"),
    ("002594", "比亚迪", "汽车"), ("601633", "长城汽车", "汽车"), ("601899", "紫金矿业", "有色"),
    ("600111", "北方稀土", "有色"), ("600048", "保利发展", "地产"), ("000002", "万科A", "地产"),
    ("600760", "中航沈飞", "军工"), ("600893", "航发动力", "军工"), ("600030", "中信证券", "券商"),
    ("300059", "东方财富", "券商"), ("688981", "中芯国际", "半导体"), ("603986", "兆易创新", "半导体"),
    ("002714", "牧原股份", "农业"), ("600598", "北大荒", "农业"), ("601006", "大秦铁路", "交运"),
    ("600009", "上海机场", "交运"), ("600941", "中国移动", "通信"), ("601728", "中国电信", "通信"),
]

def run_pool(pool, model, step_pct=0.20, cap_pct=0.30):
    """跑一个标的池，返回等权组合 summary + 逐标的交易数/胜率"""
    wsb.POSITION_MODEL = model
    wsb.STEP_PCT = step_pct
    wsb.CAP_PCT = cap_pct
    combos = {}
    per_symbol = {}
    for item in pool:
        if len(item) == 5:  # 19 池 (code,name,type,mkt,news)
            code, name, typ, mkt, news = item
        else:               # 39 池 (code,name,industry)
            code, name, _ind = item
            typ, news = "股票", None
        if len(item) == 5:  # 19 池 (code,name,type,mkt,news) → data/
            code, name, typ, mkt, news = item
            df = load_data(code)
        else:               # 39 池 (code,name,industry) → data_tmp/
            code, name, _ind = item
            typ, news = "股票", None
            import os
            from config import DATA_TMP
            fp = os.path.join(str(DATA_TMP), f"{code}.csv")
            if not os.path.exists(fp):
                continue
            df = pd.read_csv(fp)
            df["date"] = df["date"].astype(str).str.replace(r"(\d{4})(\d{2})(\d{2})", r"\1-\2-\3", regex=True)
            df["date"] = pd.to_datetime(df["date"])
            for c in ["open", "high", "low", "close"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
            df = df.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)
        eq, tr = wsb.run_backtest(df, news, is_fund=(typ == "基金"), strategy="weight")
        if not eq:
            continue
        base = eq[0]["value"]
        for p in eq:
            combos.setdefault(p["date"], []).append(100 * p["value"] / base)
        per_symbol[code] = {
            "name": name, "ret": eq[-1]["value"] / eq[0]["value"] * 100 - 100,
            "trades": len(tr),
            "win_rate": round(sum(1 for t in tr if t["pnl"] > 0) / len(tr) * 100, 1) if tr else 0,
        }
    combo = [{"date": dt, "value": round(sum(v) / len(v), 4)} for dt, v in sorted(combos.items())]
    s = compute_summary(combo, [])
    return s, per_symbol

def main():
    # 扫描配置：基线 + 增量步长5档 + 目标制上限5档
    configs = [
        ("v1.2基线(target)", "target", 0.0, 0.0),
        ("增量STEP10%", "incremental", 0.10, 0.0),
        ("增量STEP15%", "incremental", 0.15, 0.0),
        ("增量STEP20%", "incremental", 0.20, 0.0),
        ("增量STEP25%", "incremental", 0.25, 0.0),
        ("增量STEP30%", "incremental", 0.30, 0.0),
        ("目标制CAP10%", "target_cap", 0.0, 0.10),
        ("目标制CAP20%", "target_cap", 0.0, 0.20),
        ("目标制CAP30%", "target_cap", 0.0, 0.30),
        ("目标制CAP40%", "target_cap", 0.0, 0.40),
        ("目标制CAP50%", "target_cap", 0.0, 0.50),
    ]
    out = {}
    for label, model, step, cap in configs:
        s19, p19 = run_pool(wsb.UNIVERSE, model, step, cap)
        s39, p39 = run_pool(TMP_UNIVERSE, model, step, cap)
        t19 = sum(v["trades"] for v in p19.values())
        t39 = sum(v["trades"] for v in p39.values())
        out[label] = {
            "model": model, "step_pct": step, "cap_pct": cap,
            "pool19": {"total": round(s19["total_return_pct"], 2), "dd": round(s19["max_drawdown_pct"], 2),
                       "sharpe": round(s19["sharpe"], 3), "trades": t19},
            "pool39": {"total": round(s39["total_return_pct"], 2), "dd": round(s39["max_drawdown_pct"], 2),
                       "sharpe": round(s39["sharpe"], 3), "trades": t39},
        }
        print(f"{label:<20} 19池:{out[label]['pool19']['total']:>+8.1f}%(dd {out[label]['pool19']['dd']:.1f}% sh {out[label]['pool19']['sharpe']:.2f} tr {t19:>4}) | "
              f"39池:{out[label]['pool39']['total']:>+8.1f}%(dd {out[label]['pool39']['dd']:.1f}% sh {out[label]['pool39']['sharpe']:.2f} tr {t39:>4})")
    with open("position_model_compare.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("\n已保存: position_model_compare.json")

if __name__ == "__main__":
    main()
