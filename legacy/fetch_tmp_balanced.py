# -*- coding: utf-8 -*-
"""平衡领域样本扩充：13 领域 × 2 只 = 26 只临时标的（与用户 watchlist 分开）"""
import subprocess, os, csv

from config import WSTOCK_CLI as WS, DATA_TMP as OUT
os.makedirs(OUT, exist_ok=True)

# 平衡领域样本池（每领域 2 只，共 13 领域 26 只）
# 已有 12 只保留，补齐至平衡；与用户 watchlist（AI/光模块/PCB）领域刻意错开
TMP = [
    # 白酒/消费（已有茅台、五粮液）+ 伊利股份
    ("600887", "伊利股份", "sh600887", "消费"),
    # 银行（已有招行）+ 工商银行
    ("601398", "工商银行", "sh601398", "银行"),
    # 新能源（已有宁德、隆基）+ 阳光电源
    ("300274", "阳光电源", "sz300274", "新能源"),
    # 医药（已有恒瑞）+ 药明康德、迈瑞医疗
    ("603259", "药明康德", "sh603259", "医药"),
    ("300760", "迈瑞医疗", "sz300760", "医药"),
    # 家电（已有美的）+ 格力电器
    ("000651", "格力电器", "sz000651", "家电"),
    # 煤炭（已有神华）+ 陕西煤业
    ("601225", "陕西煤业", "sh601225", "煤炭"),
    # 保险（已有平安）+ 中国太保
    ("601601", "中国太保", "sh601601", "保险"),
    # 公用（已有长电）+ 三峡能源
    ("600905", "三峡能源", "sh600905", "公用"),
    # 汽车（已有比亚迪）+ 长城汽车
    ("601633", "长城汽车", "sh601633", "汽车"),
    # 有色（已有紫金）+ 北方稀土
    ("600111", "北方稀土", "sh600111", "有色"),
    # 地产（新增领域）
    ("600048", "保利发展", "sh600048", "地产"),
    ("000002", "万科A", "sz000002", "地产"),
    # 军工（新增领域）
    ("600760", "中航沈飞", "sh600760", "军工"),
    ("600893", "航发动力", "sh600893", "军工"),
    # 券商（新增领域）
    ("600030", "中信证券", "sh600030", "券商"),
    ("300059", "东方财富", "sz300059", "券商"),
    # 半导体（新增领域，但用与用户池不同的标的）
    ("688981", "中芯国际", "sh688981", "半导体"),
    ("603986", "兆易创新", "sh603986", "半导体"),
    # 农业（新增领域）
    ("002714", "牧原股份", "sz002714", "农业"),
    ("600598", "北大荒", "sh600598", "农业"),
    # 交运（新增领域）
    ("601006", "大秦铁路", "sh601006", "交运"),
    ("600009", "上海机场", "sh600009", "交运"),
    # 通信运营（新增领域）
    ("600941", "中国移动", "sh600941", "通信"),
    ("601728", "中国电信", "sh601728", "通信"),
]

def parse(text):
    lines = [l for l in text.strip().splitlines() if l.strip()]
    if not lines or "|" not in lines[0]:
        return []
    hdr = [c.strip() for c in lines[0].strip("|").split("|")]
    rows = []
    for line in lines[2:]:
        if "|" not in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != len(hdr):
            continue
        rows.append(dict(zip(hdr, cells)))
    return rows

ok = 0
fail = []
for code, name, wcode, ind in TMP:
    p = os.path.join(OUT, f"{code}.csv")
    if os.path.exists(p) and os.path.getsize(p) > 100:
        print(f"SKIP {code} {name} ({ind})")
        ok += 1
        continue
    try:
        r = subprocess.run(["node", WS, "kline", wcode, "--period", "day", "--limit", "1000", "--fq", "qfq"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        rows = parse(r.stdout)
        if not rows:
            fail.append((code, name, "空返回"))
            print(f"FAIL {code} {name}: 空返回")
            continue
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["date", "open", "high", "low", "close", "volume", "amount"])
            for row in rows:
                w.writerow([row.get("date", ""), row.get("open", ""), row.get("high", ""),
                            row.get("low", ""), row.get("last", row.get("close", "")),
                            row.get("volume", ""), row.get("amount", "")])
        print(f"OK {code} {name} ({ind}): {len(rows)} bars")
        ok += 1
    except Exception as e:
        fail.append((code, name, str(e)[:80]))
        print(f"ERR {code} {name}: {e}")

print(f"\n完成 {ok}/{len(TMP)}，失败 {len(fail)}")
for c, n, e in fail:
    print(f"  {c} {n}: {e}")
