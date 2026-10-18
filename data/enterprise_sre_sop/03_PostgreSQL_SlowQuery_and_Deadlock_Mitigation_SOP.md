# PostgreSQL 高并发慢查询治理与死锁锁争用排查手册 (SOP)

> 文档编号: SOP-SRE-PG-003  
> 适用范围: 生产 PostgreSQL 14~18 数据库集群、云端 RDS / 自建主从实例  
> 密级: 内部生产规范  

---

## 一、故障定义与严重级别

### 1.1 核心故障现象
1. **连接池耗尽 (Connection Pool Exhaustion)**:
   - 现象：应用端报错 `org.postgresql.util.PSQLException: FATAL: remaining connection slots are reserved for non-replication superuser connections` 或 HikariCP `Connection is not available, request timed out after 30000ms`。
   - 根因：长事务悬挂、慢查询挤压大量后端工作进程，导致 `max_connections` 被打满。
2. **死锁 (Deadlock Detected)**:
   - 现象：应用端捕获 `ERROR: deadlock detected (SQLSTATE 40P01)`。两个或多个事务互相持有对方等待的行锁。
3. **慢查询导致 CPU 100%**:
   - 现象：缺少索引导致大表进行顺序扫描（Seq Scan），或不合理的连接算法（Nested Loop 缺少驱动表索引）。

---

## 二、在线排障与紧急处置命令

### 2.1 实时活跃慢查询定位
```sql
-- 查询当前执行时间超过 5 秒的活跃 SQL（排除空闲连接）
SELECT 
    pid, 
    now() - pg_stat_activity.query_start AS duration, 
    usename, 
    client_addr, 
    state, 
    query 
FROM pg_stat_activity 
WHERE (now() - pg_stat_activity.query_start) > interval '5 seconds'
  AND state != 'idle'
ORDER BY duration DESC;
```

### 2.2 紧急中断或杀死阻塞查询 (Emergency Termination)
```sql
-- 1. 温和取消正在执行的查询 (软中断，相当于 SIGINT)
SELECT pg_cancel_backend(<pid>);

-- 2. 强制终止连接并回滚事务 (硬终止，相当于 SIGTERM，释放所有持有锁)
SELECT pg_terminate_backend(<pid>);
```

### 2.3 死锁与锁等待全链路分析
```sql
-- 查看当前被阻塞的进程与阻塞它的源头进程
SELECT 
    blocked_locks.pid AS blocked_pid,
    blocked_activity.usename AS blocked_user,
    blocking_locks.pid AS blocking_pid,
    blocking_activity.usename AS blocking_user,
    blocked_activity.query AS blocked_statement,
    blocking_activity.query AS current_statement_in_blocking_process
FROM pg_catalog.pg_locks blocked_locks
JOIN pg_catalog.pg_stat_activity blocked_activity ON blocked_activity.pid = blocked_locks.pid
JOIN pg_catalog.pg_locks blocking_locks 
    ON blocking_locks.locktype = blocked_locks.locktype
    AND blocking_locks.database IS NOT DISTINCT FROM blocked_locks.database
    AND blocking_locks.relation IS NOT DISTINCT FROM blocked_locks.relation
    AND blocking_locks.page IS NOT DISTINCT FROM blocked_locks.page
    AND blocking_locks.tuple IS NOT DISTINCT FROM blocked_locks.tuple
    AND blocking_locks.virtualxid IS NOT DISTINCT FROM blocked_locks.virtualxid
    AND blocking_locks.transactionid IS NOT DISTINCT FROM blocked_locks.transactionid
    AND blocking_locks.classid IS NOT DISTINCT FROM blocked_locks.classid
    AND blocking_locks.objid IS NOT DISTINCT FROM blocked_locks.objid
    AND blocking_locks.objsubid IS NOT DISTINCT FROM blocked_locks.objsubid
    AND blocking_locks.pid != blocked_locks.pid
JOIN pg_catalog.pg_stat_activity blocking_activity ON blocking_activity.pid = blocking_locks.pid
WHERE NOT blocked_locks.granted;
```

---

## 三、慢查询执行计划分析与索引治理

### 3.1 真实执行计划获取 (EXPLAIN ANALYZE)
```sql
-- 必须附带 BUFFERS 参数以观察磁盘读写开销
EXPLAIN (ANALYZE, BUFFERS, COSTS, VERBOSE)
SELECT * FROM orders WHERE user_id = 'usr_10293' AND status = 'COMPLETED';
```
- **核心判定标准**:
  - `Seq Scan on orders (cost=0.00..54210.00 ...)`: **严重警报**！大表全表扫描。必须为 `(user_id, status)` 建立复合 B-Tree 索引。
  - `Buffers: shared read=...`: 表示从 OS 磁盘直接读取的 Page 数；`shared hit=...` 表示从 PG 共享内存缓存（shared_buffers）命中的 Page 数。如果 `shared read` 极高，表明内存缓冲不足或缺少索引。

### 3.2 向量检索与全文检索索引调优 (pgvector + GIN)
对于企业级多模态知识库场景：
1. **向量检索索引**:
   ```sql
   -- 对 1024 维 BGE-m3 嵌入向量构建 HNSW 索引 (兼顾高召回与高并发 QPS)
   CREATE INDEX ON document_embeddings USING hnsw (embedding vector_cosine_ops)
   WITH (m = 16, ef_construction = 64);
   ```
2. **全文检索倒排索引 (GIN)**:
   ```sql
   -- 中文全文检索使用 GIN 倒排索引
   CREATE INDEX idx_chunks_content_gin ON document_chunks USING gin (to_tsvector('simple', content));
   ```

---

## 四、连接池配置与架构防雪崩建议

1. **引入连接池中间件 (PgBouncer)**:
   - PostgreSQL 每个客户端连接采用一个独立的 Linux 后端进程（Process-per-connection），默认并发连接超过 500 时进程上下文切换开销剧增。
   - 生产环境必须在应用与 PostgreSQL 之间部署 **PgBouncer**，采用 `pool_mode = transaction`（事务级复用），可支撑数万微服务客户端连接并发复用 100~200 个物理 DB 连接。
2. **长事务防范配置**:
   ```conf
   # 事务在空闲状态超过 30 秒自动超时断开，杜绝开发漏写 commit 锁死行
   idle_in_transaction_session_timeout = '30s'
   # 单个查询执行超过 60 秒强制中断
   statement_timeout = '60s'
   ```
