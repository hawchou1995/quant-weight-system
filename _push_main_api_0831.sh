#!/bin/bash
# 通过 gh api 推送 main：三方合并（base=3a0adc9, mine=a4d3d8f, theirs=1b797e9）
# 策略：我的收盘版覆盖池文件（收盘口径取代盘中），远端独有文件（probe）保留
set -euo pipefail
cd "D:/Documents/Workbuddy/股票基金/quant-weight-system"
OWNER="hawchou1995"; REPO="quant-weight-system"; BRANCH="main"
API="repos/$OWNER/$REPO"
BASE="3a0adc9"          # 共同祖先（本地有）
LOCAL=$(git rev-parse HEAD)   # a4d3d8f
REMOTE=$(gh api "$API/git/ref/heads/$BRANCH" --jq '.object.sha')  # 1b797e9
echo "base=$BASE local=$LOCAL remote=$REMOTE"

# 1) 我的变更清单（vs base）
mapfile -t MINE < <(git diff --name-status "$BASE" "$LOCAL")
echo "我的变更: ${#MINE[@]} 只"

# 2) 远端完整 tree
gh api "$API/git/trees/$REMOTE?recursive=1" > C:/Users/Admin/AppData/Local/Temp/qws_push/main_tree.json

# 3) 为我的新增/修改文件创建 blobs
echo '{}' > C:/Users/Admin/AppData/Local/Temp/qws_push/blob_map.json
for entry in "${MINE[@]}"; do
  st="${entry%%$'\t'*}"
  rest="${entry#*$'\t'}"
  if [[ "$st" == R* ]]; then
    # 重命名：old\tnew，新路径=第二字段
    path="${rest#*$'\t'}"
    echo "  重命名: $rest"
  else
    path="$rest"
  fi
  [ -z "$path" ] && continue
  if [ "$st" = "D" ]; then
    echo "  删除: $path"
    continue
  fi
  B64=$(base64 -w0 "$path")
  SHA=$(gh api -X POST "$API/git/blobs" --input - <<EOF | python -c "import sys,json;print(json.load(sys.stdin)['sha'])"
{"content":"$B64","encoding":"base64"}
EOF
)
  python - "$path" "$SHA" <<'PYEOF'
import json, sys
m = json.load(open('C:/Users/Admin/AppData/Local/Temp/qws_push/blob_map.json'))
m[sys.argv[1]] = sys.argv[2]
json.dump(m, open('C:/Users/Admin/AppData/Local/Temp/qws_push/blob_map.json', 'w'))
PYEOF
  echo "  blob: $path"
done

# 4) 构建合并 tree：远端全量 - 我的删除 + 我的 blob 覆盖
python - <<'PYEOF'
import json
remote_tree = json.load(open('C:/Users/Admin/AppData/Local/Temp/qws_push/main_tree.json'))['tree']
sha_map = {t['path']: t['sha'] for t in remote_tree if t['type'] == 'blob'}
blob = json.load(open('C:/Users/Admin/AppData/Local/Temp/qws_push/blob_map.json'))
deleted = set()
import subprocess
# 从 MINE 清单提取删除项
out = subprocess.run(['git', 'diff', '--name-status', '3a0adc9', 'HEAD'],
                     capture_output=True, text=True, cwd='.').stdout
for ln in out.splitlines():
    parts = ln.split('\t')
    if not parts:
        continue
    if parts[0] == 'D':
        deleted.add(parts[1])
    elif parts[0].startswith('R'):
        # 重命名：旧路径删除
        deleted.add(parts[1])
tree = []
for p in sha_map:
    if p in deleted:
        continue
    tree.append({"path": p, "mode": "100644", "type": "blob", "sha": blob.get(p, sha_map[p])})
for p, sha in blob.items():
    if p not in sha_map:
        tree.append({"path": p, "mode": "100644", "type": "blob", "sha": sha})
json.dump(tree, open('C:/Users/Admin/AppData/Local/Temp/qws_push/new_tree.json', 'w'))
print(f"合并 tree: {len(tree)} 条目（远端 {len(sha_map)} - 删除 {len(deleted)} + 覆盖/新增 {len(blob)}）")
PYEOF

# 5) 创建 tree
TREE=$(gh api -X POST "$API/git/trees" --input - <<EOF | python -c "import sys,json;print(json.load(sys.stdin)['sha'])"
{"tree": $(cat C:/Users/Admin/AppData/Local/Temp/qws_push/new_tree.json)}
EOF
)
echo "tree: $TREE"

# 6) 创建 commit（父=远端 main）
MSG=$(git log -1 --format=%s "$LOCAL")
COMMIT=$(gh api -X POST "$API/git/commits" --input - <<EOF | python -c "import sys,json;print(json.load(sys.stdin)['sha'])"
{"message":"$MSG","tree":"$TREE","parents":["$REMOTE"]}
EOF
)
echo "commit: $COMMIT"

# 7) 更新 ref
gh api -X PATCH "$API/git/refs/heads/$BRANCH" --input - <<EOF
{"sha":"$COMMIT","force":false}
EOF
echo "✅ main 推送完成"
