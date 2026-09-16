# -*- coding: utf-8 -*-
"""行业上限选择的干净实现 + 单元测试（R-buffett-opt3-0915 地基修复）。

背景（必须记住的教训）：
  value_opt4/opt5 里的上限选择出现"两条逻辑等价的代码路径产出不同选择集"
  （grp.iloc[ci] 键 → 16.09%/−35.74%；'IND:'+code 键 → 15.32%/−42.29%），
  排查到"key 字符串全量相等、无 NaN、同为 31 类"仍未定位 → 说明问题在
  **算法实现层而非数据层**。本模块把选择逻辑抽成**纯函数**，用合成用例把
  期望值写死做断言，任何歧义都会在单测里暴露。

设计原则（避免重蹈覆辙）：
  1. 纯 numpy 实现，**不碰 pandas**（pandas 3.0 的 string dtype / 只读数组 / 对齐语义都是已知雷区）
  2. key 一律先转成**确定性的整数编码**（interned group id），杜绝标量类型差异
  3. `np.argsort` 用 `kind="stable"`，并列时按**列序**确定性打破
  4. 输出 = 选中的列索引列表，顺序即优先级（0 最优）
"""
import numpy as np


def encode_keys(keys):
    """任意可哈希 key 序列 → 确定性整数 id（按首次出现顺序）。"""
    m, out = {}, []
    for k in keys:
        ks = str(k)
        if ks not in m:
            m[ks] = len(m)
        out.append(m[ks])
    return np.asarray(out, dtype=np.int64), m


def select_with_cap(row, group_id, topn, cap=1, max_group=None):
    """贪心选择：按 row 升序（小=优）取 topn，且任一 group 不超过 cap。

    row      : 1-D float 分数数组（NaN/inf = 不可选）
    group_id : 1-D int 行业编码，与 row 等长
    topn     : 目标只数
    cap      : 每行业上限
    max_group: 可选，额外的一组编码（如风险簇），同样受 cap 限制
    返回      : 选中列索引列表（按优先级）
    """
    row = np.asarray(row, dtype=np.float64)
    gid = np.asarray(group_id, dtype=np.int64)
    ok = np.isfinite(row)
    if ok.sum() < topn:
        return []
    order = np.argsort(np.where(ok, row, np.inf), kind="stable")   # 稳定排序，并列按列序
    cnt, pick = {}, []
    for ci in order:
        ci = int(ci)
        if not ok[ci]:
            break
        g = int(gid[ci])
        if cnt.get(g, 0) >= cap:
            continue
        if max_group is not None:
            g2 = int(np.asarray(max_group)[ci])
            if cnt.get(("c", g2), 0) >= cap:
                continue
            cnt[("c", g2)] = cnt.get(("c", g2), 0) + 1
        cnt[g] = cnt.get(g, 0) + 1
        pick.append(ci)
        if len(pick) == topn:
            break
    return pick


# ---------------------------------------------------------------- 单元测试
def _t(name, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name}\n        got  {got}\n        want {want}")
    return ok


def self_test():
    print("=" * 78)
    print("单测：行业上限选择（合成数据，期望值手工写死）")
    print("=" * 78)
    allok = True

    # 用例1：无重复行业 → 应取分数最小的 top5，顺序=优先级
    row = np.array([0.5, 0.1, 0.3, 0.2, 0.4, 0.9])
    gid, _ = encode_keys(["A", "B", "C", "D", "E", "F"])
    allok &= _t("无重复行业 cap=1 top5", select_with_cap(row, gid, 5, 1), [1, 3, 2, 4, 0])

    # 用例2：全同行业 cap=1 → 只能取 1 只（最优）
    gid2, _ = encode_keys(["X"] * 6)
    allok &= _t("全同行业 cap=1", select_with_cap(row, gid2, 5, 1), [1])

    # 用例3：混合，手工推导
    #   分数序：B(0.1) D(0.2) C(0.3) E(0.4) A(0.5) F(0.9)
    #   行业：  A=A钱  B=B钱  C=A钱  D=B钱  E=C钱  F=D钱
    #   cap=1: 取 B(B钱) → D(B钱已被占,跳过) → C(A钱) → E(C钱) → A(A钱已被占,跳过) → F(D钱)
    #   → 期望 [1,2,4,5]（原写 [1,2,3,5] 是我手推漏了 idx3 的行业冲突）
    gid3, _ = encode_keys(["A钱", "B钱", "A钱", "B钱", "C钱", "D钱"])
    allok &= _t("混合 cap=1", select_with_cap(row, gid3, 4, 1), [1, 2, 4, 5])

    # 用例4：cap=2 同一数据 → B、D 都可入
    #   序：B(0.1) D(0.2) C(0.3) E(0.4) A(0.5) F(0.9)
    #   cap=2: B(B钱1) D(B钱2) C(A钱1) E(C钱1) A(A钱2) F(D钱1) → 取前4 = [1,3,2,4]
    allok &= _t("混合 cap=2", select_with_cap(row, gid3, 4, 2), [1, 3, 2, 4])

    # 用例5：并列分数 → 稳定排序应给列序在前者
    row5 = np.array([0.1, 0.1, 0.1, 0.5])
    gid5, _ = encode_keys(["A", "A", "A", "B"])
    allok &= _t("全并列 cap=1（应取列序最小）", select_with_cap(row5, gid5, 2, 1), [0, 3])

    # 用例6：NaN/inf 不可选
    row6 = np.array([np.nan, 0.2, np.inf, 0.1])
    gid6, _ = encode_keys(["A", "B", "C", "D"])
    allok &= _t("NaN/inf 排除(topn=2)", select_with_cap(row6, gid6, 2, 1), [3, 1])

    # 用例7：可选数不足 topn
    row7 = np.array([0.1, np.nan, np.nan])
    gid7, _ = encode_keys(["A", "B", "C"])
    allok &= _t("有效数不足", select_with_cap(row7, gid7, 3, 1), [])

    # 用例8：确定性——同输入跑 50 次结果必须逐位相同
    picks = {tuple(select_with_cap(row, gid3, 4, 1)) for _ in range(50)}
    allok &= _t("确定性（50 次同结果）", len(picks), 1)

    # 用例9：key 类型不得影响结果（str / np.str_ / 带前缀）
    a = select_with_cap(row, encode_keys(["A钱", "B钱", "A钱", "B钱", "C钱", "D钱"])[0], 4, 1)
    b = select_with_cap(row, encode_keys([np.str_("A钱"), np.str_("B钱"), np.str_("A钱"),
                                          np.str_("B钱"), np.str_("C钱"), np.str_("D钱")])[0], 4, 1)
    c = select_with_cap(row, encode_keys(["IND:A钱", "IND:B钱", "IND:A钱", "IND:B钱",
                                          "IND:C钱", "IND:D钱"])[0], 4, 1)
    allok &= _t("key 类型无关性(str/np.str_/前缀)", (a, b, c), ([1, 2, 4, 5],) * 3)

    print("=" * 78)
    print(f"单测总判定：{'ALL PASS' if allok else 'FAIL —— 禁止上真实数据'}")
    print("=" * 78)
    return allok


if __name__ == "__main__":
    import sys
    sys.exit(0 if self_test() else 1)
