# -*- coding: utf-8 -*-
"""audit_chain_imports.py — 审计「链步骤导入的本地模块是否都已入库」（R-cloud-imports-0927）

动机：云端 checkout 只含**已入库**文件。若某链步骤 import 一个「本机存在但被 .gitignore 挡住」的
模块，云端会 ImportError → 该步 [软] 失败 → 看板对应数据静默停更（实测：热榜哨兵
sentinel_daily 因 backtest/jiandi_signal_0906.py 被 .gitignore:305 忽略而长期失败）。

只读审计：解析 daily_refresh.py 的 STEPS 脚本 + 各脚本的本地 import，报告未入库者。
"""
import ast, pathlib, re, subprocess, sys

R = pathlib.Path(__file__).resolve().parent
bt = R / "backtest"

def tracked():
    out = subprocess.run(["git", "ls-files"], cwd=str(R), capture_output=True, text=True)
    return set(out.stdout.splitlines())

def local_modules():
    """本机存在的可导入模块名 -> 路径"""
    m = {}
    for d in (R, bt):
        for f in d.glob("*.py"):
            m.setdefault(f.stem, []).append(f.relative_to(R).as_posix())   # 必须用 / ，否则与 git ls-files 不匹配（Windows 下是 \）
    return m

def chain_scripts():
    s = (R / "daily_refresh.py").read_text(encoding="utf-8")
    i = s.find("STEPS = [")
    j = s.find("\n]", i)
    blk = s[i:j]
    return re.findall(r'\["([^"]+\.py)"', blk)

def imports_of(p):
    try:
        t = ast.parse(pathlib.Path(p).read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return set()
    out = set()
    for n in ast.walk(t):
        if isinstance(n, ast.Import):
            for al in n.names:
                out.add(al.name.split(".")[0])
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            out.add(n.module.split(".")[0])
    return out

def main():
    tk = tracked(); lm = local_modules()
    steps = chain_scripts()
    print("链步骤脚本 = %d 个" % len(steps))
    bad = {}
    for rel in steps:
        if not (R / rel).exists():
            print("  !! 脚本不在盘: %s" % rel); continue
        for mod in sorted(imports_of(R / rel)):
            if mod not in lm:
                continue                            # 不是本地模块（第三方/标准库）
            for path in lm[mod]:
                if path not in tk:
                    bad.setdefault(mod, set()).add((rel, path))
    if not bad:
        print("\n✅ 未发现「链步骤导入但未入库」的本地模块")
        return 0
    print("\n❌ 发现 %d 个「本机存在、但未入库」的本地模块被链步骤导入：" % len(bad))
    for mod, who in sorted(bad.items()):
        print("  - %s" % mod)
        for rel, path in sorted(who)[:4]:
            print("        路径 %s   被 %s 导入" % (path, rel))
    print("\n修法：`git add -f <path>`（若忽略规则是误加，应改 .gitignore 而非长期 -f）")
    return 1

if __name__ == "__main__":
    sys.exit(main())
