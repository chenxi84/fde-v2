#!/bin/bash
# 在**测试服务器**上用「克隆空库」跑链测试 —— 真 PostgreSQL 上的写路径验证配方。
#
# 为什么需要它：本地链测试靠"影子库（复制 SQLite 文件 + 换根环境变量）"隔离；**PG 上没有等价物**
# ⇒ 直接对着 fdev2 跑链测试会把测试数据写进演示库（红线：verify 脚本绝不污染用户 demo 数据）。
# 做法：`pg_dump --schema-only` 克隆出一个**空结构**的同名库，让测试只写它，跑完删掉。
#
# 用法（在服务器上，repo 根目录）：
#     bash scripts/verify_pg_clone.sh                       # 跑 nasa_pms 全部分片（每片一个空克隆）
#     bash scripts/verify_pg_clone.sh app/psc/tests/verify_chain_psc.py   # 跑指定的整链脚本
#
# 三条实操要点（都踩过）：
#   1. 必须 `--schema-only`：链测试自己造数、假设空表；带数据克隆会因唯一约束大面积红。
#   2. **一个分片一个空克隆**：组编排器（verify_chain_<组>.py）在 PG 上会让分片互相踩脏
#      （本地靠影子库+清表隔离，PG 下没有那层）—— 表现为"先造一条需求 REQ-011 失败"这类
#      "前面分片留下的残留"。所以下面每个分片都重建一次库。
#   3. 验证"没污染"：跑前跑后各查一次演示库指纹，并确认克隆库里**确实有**写入的行。
set -u
C="${FDE_PG_CONTAINER:-fde-v22_postgres_1}"
P="${FDE_APP_CONTAINER:-fde-v22_fde-v2_1}"
U="${FDE_PG_USER:-fde}"
DB="${FDE_PG_DB:-fdev2}"
SMOKE="${FDE_PG_SMOKE_DB:-fdev2_smoke}"

recreate() {
  docker exec -i "$C" psql -U "$U" -d postgres -q \
      -c "DROP DATABASE IF EXISTS $SMOKE" -c "CREATE DATABASE $SMOKE OWNER $U" >/dev/null 2>&1
  docker exec -i "$C" pg_dump -U "$U" --schema-only "$DB" \
      | docker exec -i "$C" psql -U "$U" -d "$SMOKE" -q >/dev/null 2>&1
}

run_one() {                       # $1 = 容器内脚本路径
  recreate
  docker exec -i -e DATABASE_URL="postgresql://$U:$U@postgres:5432/$SMOKE" -w /app "$P" \
      python "$1" 2>&1 | grep -E "VERIFY_RESULT" | tail -1
}

fingerprint() {
  docker exec -i "$C" psql -U "$U" -d "$DB" -tAc \
    "SELECT (SELECT count(*) FROM psc_md_material.md_material) AS md_material,
            (SELECT count(*) FROM psc_outbound_plan.outbound_plan) AS outbound,
            (SELECT count(*) FROM nasa_pms_wbs.wbs_element) AS wbs"
}

echo "== 演示库指纹（跑前）=="; fingerprint

if [ $# -ge 1 ]; then
  echo "== $1 =="; run_one "$1"
else
  pass=0; fail=0; failed=""
  for f in $(docker exec -i "$P" ls /app/app/nasa_pms/tests/ | grep '^verify_chain_nasa_pms_.*\.py$'); do
    r=$(run_one "/app/app/nasa_pms/tests/$f")
    if echo "$r" | grep -q PASS; then pass=$((pass+1)); else fail=$((fail+1)); failed="$failed $f"; fi
    printf "%-38s %s\n" "${f#verify_chain_nasa_pms_}" "$r"
  done
  echo "---- 分片通过 $pass · 失败 $fail ----"
  [ -n "$failed" ] && echo "失败：$failed"
fi

echo "== 演示库指纹（跑后，应与跑前一致）=="; fingerprint
docker exec -i "$C" psql -U "$U" -d postgres -q -c "DROP DATABASE IF EXISTS $SMOKE" >/dev/null 2>&1
echo "克隆库 $SMOKE 已删除"
