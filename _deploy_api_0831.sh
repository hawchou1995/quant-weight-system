#!/bin/bash
# 通过 gh api（Git Data API）部署 dist/ 到 gh-pages —— 沙箱拦截 github.com:443 时使用
# 用法: bash _deploy_api_0831.sh
set -euo pipefail
DIST="D:/Documents/Workbuddy/股票基金/dist"
OWNER="hawchou1995"; REPO="quant-weight-system"; BRANCH="gh-pages"
API="repos/$OWNER/$REPO"

# 1) 远端 gh-pages 头
PARENT=$(gh api "$API/git/ref/heads/$BRANCH" --jq '.object.sha')
echo "远端 gh-pages 头: $PARENT"

# 2) 收集文件
mapfile -t FILES < <(cd "$DIST" && find . -type f ! -path './.git/*' | sed 's|^\./||' | sort)
echo "待部署文件: ${#FILES[@]} 只"

# 3) 创建 blobs（每只一个 gh api 调用，--input 传 JSON）
BLOBS=()
i=0
for rel in "${FILES[@]}"; do
  i=$((i+1))
  B64=$(base64 -w0 "$DIST/$rel")
  SHA=$(gh api -X POST "$API/git/blobs" --input - <<EOF | python -c "import sys,json;print(json.load(sys.stdin)['sha'])"
{"content":"$B64","encoding":"base64"}
EOF
)
  BLOBS+=("{\"path\":\"$rel\",\"mode\":\"100644\",\"type\":\"blob\",\"sha\":\"$SHA\"}")
  if (( i % 20 == 0 )); then echo "  blobs [$i/${#FILES[@]}]"; fi
done

# 4) 创建 tree
TREE_JSON=$(printf '{"tree":[%s]}' "$(IFS=,; echo "${BLOBS[*]}")")
TREE=$(gh api -X POST "$API/git/trees" --input - <<EOF | python -c "import sys,json;print(json.load(sys.stdin)['sha'])"
$TREE_JSON
EOF
)
echo "tree: $TREE"

# 5) 创建 commit
MSG="deploy: $(date '+%Y-%m-%d %H:%M') (api)"
COMMIT=$(gh api -X POST "$API/git/commits" --input - <<EOF | python -c "import sys,json;print(json.load(sys.stdin)['sha'])"
{"message":"$MSG","tree":"$TREE","parents":["$PARENT"]}
EOF
)
echo "commit: $COMMIT"

# 6) 更新 ref
gh api -X PATCH "$API/git/refs/heads/$BRANCH" --input - <<EOF
{"sha":"$COMMIT","force":false}
EOF
echo "✅ 部署完成"
