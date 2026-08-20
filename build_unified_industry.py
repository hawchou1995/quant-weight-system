# -*- coding: utf-8 -*-
"""全市场统一行业池生成（2026-08-20 · 消灭「综合」兜底）v2
=================================================================
目标：所有脚本（limit_up_follow / sector_radar / build_enhanced_data / 看板）共用同一套行业分类。
数据源优先级：
  1. 申万一级行业成分（akshare sw_index_first_info + index_component_sw，覆盖全 A 股 5207 只）
  2. build_enhanced_data.py 内的 INDUSTRY / ETF_INDUSTRY（ast 正确解析，覆盖 127 只硬编码 + ETF 主题）
  3. 名称关键词（A股/ETF/LOF/北交所全覆盖；不再返回「综合」，识别不出归「其他」）
输出：quant-weight-system/stock_industry.json
  { version, source, map:{ code6:行业 }, meta, universe }
"""
import os, re, json, sys, time, ast
from pathlib import Path
BASE = Path(os.path.dirname(os.path.abspath(__file__)))

# ================= 1. 申万一级行业成分 =================
print("拉取申万一级行业成分…", flush=True)
import akshare as ak
sw = {}
sw_zhonghe = []  # 申万「综合」行业标的（需细分）
try:
    info = ak.sw_index_first_info()
    for _, r in info.iterrows():
        code = str(r["行业代码"]).replace(".SI", "")
        name = r["行业名称"]
        try:
            comp = ak.index_component_sw(symbol=code)
            for _, row in comp.iterrows():
                stock = str(row["证券代码"]).zfill(6)
                if name == "综合":
                    sw_zhonghe.append(stock)
                else:
                    sw[stock] = name
            print(f"  {name}: {len(comp)} 只", flush=True)
        except Exception as e:
            print(f"  {name}: 失败 {str(e)[:80]}", flush=True)
        time.sleep(0.3)
except Exception as e:
    print("申万拉取失败:", str(e)[:200], flush=True)
print(f"申万一级行业映射: {len(sw)} 只 + 综合待细分 {len(sw_zhonghe)} 只", flush=True)

# ================= 2. 本地硬编码（ast 解析，兼容单引号+注释）=================
def parse_dict_literal(attr_src):
    """从 python 源码提取 dict 字面量（含注释），用 ast 求值"""
    try:
        tree = ast.parse(attr_src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
                d = {}
                for k, v in zip(node.value.keys, node.value.values):
                    if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):
                        d[str(k.value).zfill(6)] = str(v.value)
                return d
    except Exception as e:
        print("  ast 解析失败:", str(e)[:100])
    return {}

local = {}
try:
    src = (BASE / "build_enhanced_data.py").read_text(encoding="utf-8")
    # 用 ast 解析整个文件，取出顶层 Dict 赋值
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            target = node.targets[0] if node.targets else None
            name = getattr(target, "id", "") if isinstance(target, ast.Name) else ""
            if name in ("INDUSTRY", "ETF_INDUSTRY") and isinstance(node.value, ast.Dict):
                d = {}
                for k, v in zip(node.value.keys, node.value.values):
                    if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):
                        vv = str(v.value)
                        # 2026-08-20：宽基指数 ETF 不再归「综合」，归「指数宽基」
                        if vv == "综合":
                            vv = "指数宽基"
                        d[str(k.value).zfill(6)] = vv
                local.update(d)
                print(f"  本地 {name}: {len(d)} 条", flush=True)
except Exception as e:
    print("本地映射读取失败:", str(e)[:120], flush=True)
print(f"本地硬编码合计: {len(local)} 条", flush=True)

# ================= 3. 全市场标的清单 =================
names = {}
try:
    nm_raw = json.load(open(BASE / "data_full_names.json", encoding="utf-8"))
    for code, nm in nm_raw.items():
        names[str(code)[-6:]] = str(nm)
except Exception as e:
    print("names 加载失败:", str(e)[:120], flush=True)

csv_codes = {Path(f).stem[-6:] for f in os.listdir(BASE / "data_full") if f.endswith(".csv")}
universe = set(names.keys()) | csv_codes
print(f"全市场标的规模: {len(universe)}（names {len(names)} + csv {len(csv_codes)}）", flush=True)

# ================= 4. 名称关键词（A股/ETF/LOF/北交所全覆盖，不返回综合）=================
KEY = [
    # 医药
    ("药","医药生物"),("生物","医药生物"),("医疗","医药生物"),("疫苗","医药生物"),
    ("创新药","医药生物"),("制药","医药生物"),("药业","医药生物"),("基因","医药生物"),("细胞","医药生物"),
    ("CRO","医药生物"),("检测","医药生物"),("诊断","医药生物"),("体外","医药生物"),("血液","医药生物"),
    ("眼科","医药生物"),("牙科","医药生物"),("整形","医药生物"),("康复","医药生物"),("医院","医药生物"),
    # 电子/半导体
    ("半导","电子"),("芯片","电子"),("集成","电子"),("微电","电子"),("光电","电子"),("面板","电子"),
    ("LED","电子"),("PCB","电子"),("存储","电子"),("封测","电子"),("MLCC","电子"),("元件","电子"),
    ("电容","电子"),("晶振","电子"),("电子","电子"),("光学","电子"),
    # 计算机/软件/AI
    ("软件","计算机"),("数据","计算机"),("AI","计算机"),("智能","计算机"),("信息","计算机"),
    ("网络","计算机"),("数字","计算机"),("IT","计算机"),("科技","计算机"),("安全","计算机"),
    # 通信
    ("通信","通信"),("光模块","通信"),("光通信","通信"),("5G","通信"),("6G","通信"),
    ("射频","通信"),("基站","通信"),("北斗","通信"),
    # 金融
    ("证券","非银金融"),("保险","非银金融"),("期货","非银金融"),("信托","非银金融"),
    ("银行","银行"),("券商","非银金融"),
    # 地产/建筑
    ("地产","房地产"),("置业","房地产"),("物业","房地产"),("城建","房地产"),("城投","房地产"),
    ("建工","建筑装饰"),("建设","建筑装饰"),("建筑","建筑装饰"),("装饰","建筑装饰"),("园林","建筑装饰"),
    ("基建","建筑装饰"),("工程","建筑装饰"),("钢构","建筑装饰"),("设计","建筑装饰"),
    # 电力设备/新能源
    ("新能源","电力设备"),("光伏","电力设备"),("电池","电力设备"),("锂电","电力设备"),("动力","电力设备"),
    ("储能","电力设备"),("风电","电力设备"),("电网","电力设备"),("特高压","电力设备"),("电气","电力设备"),
    ("充电","电力设备"),("逆变","电力设备"),("氢能","电力设备"),
    # 有色
    ("稀土","有色金属"),("黄金","有色金属"),("有色","有色金属"),("铜业","有色金属"),("铝业","有色金属"),
    ("钼","有色金属"),("钨","有色金属"),("锌","有色金属"),("锂","有色金属"),("钴","有色金属"),
    ("矿业","有色金属"),("钨","有色金属"),
    # 化工
    ("化工","基础化工"),("材料","基础化工"),("塑料","基础化工"),("轮胎","基础化工"),("化纤","基础化工"),
    ("涂料","基础化工"),("树脂","基础化工"),("橡胶","基础化工"),("农药","基础化工"),("化肥","基础化工"),
    ("硅料","基础化工"),("氟","基础化工"),("磷","基础化工"),
    # 机械
    ("机器人","机械设备"),("机械","机械设备"),("装备","机械设备"),("工业母机","机械设备"),
    ("机床","机械设备"),("重工","机械设备"),("自动化","机械设备"),("智能制造","机械设备"),
    ("轴承","机械设备"),("减速","机械设备"),("丝杠","机械设备"),
    # 汽车
    ("汽车","汽车"),("整车","汽车"),("零部件","汽车"),("汽配","汽车"),("电动","汽车"),("客车","汽车"),
    # 军工
    ("军工","国防军工"),("国防","国防军工"),("航空","国防军工"),("航天","国防军工"),("船舶","国防军工"),
    ("兵器","国防军工"),("导航","国防军工"),
    # 食品饮料
    ("白酒","食品饮料"),("食品","食品饮料"),("饮料","食品饮料"),("乳业","食品饮料"),("啤酒","食品饮料"),
    ("调味","食品饮料"),("预制","食品饮料"),("零食","食品饮料"),
    # 农业
    ("农业","农林牧渔"),("养殖","农林牧渔"),("种业","农林牧渔"),("饲料","农林牧渔"),("畜牧","农林牧渔"),
    ("渔业","农林牧渔"),("水产","农林牧渔"),("牧业","农林牧渔"),
    # 传媒
    ("传媒","传媒"),("游戏","传媒"),("出版","传媒"),("影视","传媒"),("广告","传媒"),("文化","传媒"),("IP","传媒"),
    # 纺服
    ("纺织","纺织服饰"),("服装","纺织服饰"),("家纺","纺织服饰"),("服饰","纺织服饰"),("鞋","纺织服饰"),
    # 公用/环保
    ("电力","公用事业"),("燃气","公用事业"),("水务","公用事业"),("环保","环保"),("节能","环保"),("环境","环保"),
    # 家电/轻工
    ("家电","家用电器"),("电器","家用电器"),("厨电","家用电器"),
    ("家居","轻工制造"),("家具","轻工制造"),("造纸","轻工制造"),("包装","轻工制造"),("印刷","轻工制造"),
    ("文具","轻工制造"),("玩具","轻工制造"),
    # 建材/钢铁
    ("建材","建筑材料"),("水泥","建筑材料"),("玻璃","建筑材料"),("瓷砖","建筑材料"),
    ("钢铁","钢铁"),("特钢","钢铁"),("不锈钢","钢铁"),
    # 煤炭/石油
    ("煤炭","煤炭"),("焦","煤炭"),("石油","石油石化"),("石化","石油石化"),("炼化","石油石化"),
    ("油服","石油石化"),("油气","石油石化"),
    # 商贸/社服/美容
    ("零售","商贸零售"),("商业","商贸零售"),("百货","商贸零售"),("免税","商贸零售"),("超市","商贸零售"),
    ("电商","商贸零售"),("贸易","商贸零售"),
    ("物流","交通运输"),("航运","交通运输"),("港口","交通运输"),("海运","交通运输"),("快递","交通运输"),
    ("铁路","交通运输"),("交通","交通运输"),("机场","交通运输"),
    ("旅游","社会服务"),("酒店","社会服务"),("教育","社会服务"),("餐饮","社会服务"),
    ("美容","美容护理"),("医美","美容护理"),("化妆品","美容护理"),("护肤","美容护理"),
    # 交通运输
    ("公路","交通运输"),("航空","交通运输"),
]

def kw_industry(name):
    for kw, ind in KEY:
        if kw in name:
            return ind
    return ""

# ETF 主题关键词
ETF_KEY = [
    ("证券","非银金融"),("保险","非银金融"),("银行","银行"),
    ("医药","医药生物"),("医疗","医药生物"),("生物","医药生物"),("疫苗","医药生物"),("创新药","医药生物"),
    ("半导体","电子"),("芯片","电子"),("电子","电子"),("科创","电子"),("创新","电子"),
    ("计算机","计算机"),("软件","计算机"),("大数据","计算机"),("AI","计算机"),("人工智能","计算机"),
    ("通信","通信"),("5G","通信"),("云计算","计算机"),
    ("新能源","电力设备"),("光伏","电力设备"),("电池","电力设备"),("储能","电力设备"),("新能源汽车","汽车"),
    ("军工","国防军工"),("国防","国防军工"),
    ("黄金","有色金属"),("有色","有色金属"),("稀土","有色金属"),("有色金属","有色金属"),
    ("化工","基础化工"),("材料","基础化工"),
    ("机械","机械设备"),("机器人","机械设备"),
    ("食品","食品饮料"),("消费","食品饮料"),("酒","食品饮料"),("白酒","食品饮料"),
    ("农业","农林牧渔"),("养殖","农林牧渔"),
    ("传媒","传媒"),("游戏","传媒"),
    ("房地产","房地产"),("地产","房地产"),
    ("煤炭","煤炭"),("能源","煤炭"),("电力","公用事业"),
    ("家电","家用电器"),("汽车","汽车"),
    ("沪深300","指数宽基"),("中证500","指数宽基"),("中证1000","指数宽基"),("中证800","指数宽基"),
    ("上证50","指数宽基"),("上证180","指数宽基"),("创业板","指数宽基"),("科创板","指数宽基"),("双创","指数宽基"),
    ("A50","指数宽基"),("A500","指数宽基"),("MSCI","指数宽基"),("标普","指数宽基"),("纳指","指数宽基"),
    ("沪深","指数宽基"),("指数","指数宽基"),("中证","指数宽基"),("国证","指数宽基"),("大盘","指数宽基"),
    ("红利","策略"),("低波","策略"),("价值","策略"),("成长","策略"),("质量","策略"),("增强","策略"),
    ("等权","策略"),("优选","策略"),("龙头","策略"),
    ("债券","债券"),("信用","债券"),("国债","债券"),("债","债券"),("货币","货币"),
    ("港股","港股权限"),("恒生","港股权限"),("香港","港股权限"),("H股","港股权限"),("QDII","港股权限"),
    ("黄金","商品"),("商品","商品"),("原油","商品"),("豆粕","商品"),("能源化","商品"),("有色金属","商品"),("有色","商品"),
]

def etf_industry(name):
    for kw, ind in ETF_KEY:
        if kw in name:
            return ind
    return ""

def is_etf_lof(code, name):
    if "ETF" in name.upper() or "LOF" in name.upper():
        return True
    if code.startswith(("5", "1")):
        return True
    return False

def is_bj(code):
    return code.startswith(("4", "8", "9")) and not code.startswith(("900",)) or code.startswith("43") or code.startswith("83") or code.startswith("87") or code.startswith("92")

# ================= 5. 汇总生成 =================
result = {}
meta = {"sw1": 0, "sw1zw": 0, "local": 0, "kw": 0, "etf": 0, "bj": 0, "other": 0}
for code in sorted(universe):
    c = str(code).zfill(6)
    nm = names.get(c, "")
    # 1) 申万一级（排除综合行业）
    if c in sw:
        result[c] = sw[c]; meta["sw1"] += 1; continue
    # 2) 本地硬编码
    if c in local:
        result[c] = local[c]; meta["local"] += 1; continue
    # 3) 申万综合行业 20 只 → 关键词细分
    if c in sw_zhonghe:
        ind = kw_industry(nm)
        result[c] = ind or "其他"
        meta["sw1zw"] += 1; continue
    # 4) ETF/LOF → 主题关键词
    if is_etf_lof(c, nm):
        result[c] = etf_industry(nm) or "其他"
        meta["etf"] += 1; continue
    # 5) 北交所 → 关键词
    if is_bj(c):
        result[c] = kw_industry(nm) or "其他"
        meta["bj"] += 1; continue
    # 6) 一般股票关键词
    ind = kw_industry(nm)
    if ind:
        result[c] = ind; meta["kw"] += 1; continue
    # 7) 无法识别 → 其他（绝不综合）
    result[c] = "其他"; meta["other"] += 1

out = {
    "version": "2026-08-20",
    "source": "申万一级(akshare,5207)+本地INDUSTRY/ETF(127)+名称关键词(全市场); 已消灭综合兜底,识别不出归其他",
    "map": result,
    "meta": meta,
    "universe": len(universe),
}
with open(BASE / "stock_industry.json", "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False)
print(f"\n已写 stock_industry.json: 共 {len(result)} 只")
print(f"  sw1={meta['sw1']} local={meta['local']} 综合细分={meta['sw1zw']} kw={meta['kw']} etf={meta['etf']} bj={meta['bj']} other={meta['other']}")
print(f"  「综合」残留: {sum(1 for v in result.values() if v=='综合')}")
print(f"  「其他」: {sum(1 for v in result.values() if v=='其他')}")
