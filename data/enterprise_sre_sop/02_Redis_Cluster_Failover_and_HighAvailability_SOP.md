# Redis 分布式集群故障转移与雪崩/击穿/穿透高可用处置规范 (SOP)

> 文档编号: SOP-SRE-REDIS-002  
> 适用范围: 生产 Redis Cluster 集群、Sentinel 哨兵集群、微服务多级缓存  
> 密级: 内部生产规范  

---

## 一、故障场景与应急定义

### 1.1 缓存三大典型故障
1. **缓存穿透 (Cache Penetration)**:
   - 现象：客户端查询大量既不在缓存中、也不在数据库中的非存在数据（如恶意扫描 ID=-1 或随机 UUID）。请求直接绕过缓存冲击底层数据库，导致数据库 CPU 瞬间打满 100%。
   - 处置标准：采用**布隆过滤器 (Bloom Filter)** 提前在网关/应用层拦截；或对查询为空的结果写入带有短 TTL（如 30s~60s）的空对象。
2. **缓存击穿 (Cache Breakdown)**:
   - 现象：某个拥有超高并发访问量的热点 Key（如秒杀商品、爆款热搜）在到期瞬间失效，瞬间成千上万并发并发请求同时打向数据库重新加载。
   - 处置标准：**互斥锁 (Distributed Mutex)** 重建缓存；或采用**逻辑过期 (Logical Expiration)** 异步后台刷新。
3. **缓存雪崩 (Cache Avalanche)**:
   - 现象：大量缓存 Key 设置了相同的过期时间（如整点 00:00:00），到期时集体失效；或者 Redis 整个主节点宕机，导致所有流量全盘落向数据库引起雪崩。
   - 处置标准：Key 过期时间增加随机浮动值（如 `base_ttl + rand(0, 300)s`）；构建本地 Caffeine + Redis 分布式多级缓存。

---

## 二、热点 Key 与大 Key 线上诊断手册

### 2.1 大 Key (BigKey) 诊断与处理
- **BigKey 危害**: 内存空间严重倾斜；执行 `DEL` 或 `HGETALL` 等 $O(N)$ 命令导致单线程事件循环阻塞数百毫秒，触发客户端连接超时与集群掉线。
- **在线扫描命令**:
  ```bash
  # 1. 扫描当前实例占用内存最大的 Key (非阻塞低开销扫描)
  redis-cli -h <host> -p <port> -a <password> --bigkeys

  # 2. 精确获取特定 Key 的实际内存占用字节数
  redis-cli -h <host> -p <port> -a <password> MEMORY USAGE <key_name>
  ```
- **删除规范**: 生产环境**严禁直接执行 `DEL bigkey`**！必须采用异步非阻塞命令：
  ```bash
  # String 类型大 Key
  UNLINK <key_name>

  # Hash / Set / ZSet 渐进式删除
  HSCAN / SSCAN / ZSCAN 批量迭代分段删除，或在配置中开启:
  lazyfree-lazy-eviction yes
  lazyfree-lazy-expire yes
  lazyfree-lazy-server-del yes
  ```

### 2.2 热 Key (HotKey) 实时倾斜定位
- **诊断方式**:
  ```bash
  # 开启热点 Key 统计 (需开启 LFU 淘汰策略)
  redis-cli -h <host> -p <port> -a <password> --hotkeys
  
  # 实时监视客户端请求流量采样
  redis-cli -h <host> -p <port> -a <password> monitor | head -n 500
  ```
- **生产解决**:
  1. **本地内存二级缓存 (Caffeine / Guava Cache)**: 将 HotKey 加载进微服务本地 JVM 内存，设置短 TTL（如 3~5 秒），阻断 99% 流量到达 Redis。
  2. **加随机后缀分片 (Key Sharding)**: 将 `hotkey` 裂变为 `hotkey_0`, `hotkey_1` ... `hotkey_9`，客户端根据 Hash 取模均匀打乱在 Redis Cluster 不同 Master 节点上。

---

## 三、分布式锁安全性规范与 Lua 脚本标准

### 3.1 核心要求
生产环境使用 Redis 实现分布式锁，必须确保**加锁与解锁的原子性**，并防范误删他人锁与死锁。

### 3.2 标准原子加锁与解锁
```python
# 1. 加锁规范：必须附带全局唯一 RequestID (UUID) + NX 互斥 + PX 毫秒超时
# 命令：SET resource_lock <unique_request_id> NX PX 30000

# 2. 解锁规范：必须使用 Lua 脚本校验拥有者，保证原子释放
RELEASE_LOCK_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""
```

### 3.3 Redlock 算法适用边界与建议
- Redlock（红锁）在依赖物理时钟漂移和网络分区时存在理论缺陷（Martin Kleppmann 论战）。
- 对于强金融一致性场景（如银行转账、库存硬扣减），推荐使用数据库行锁配合悲观锁/乐观锁版本号，或采用 Apache ZooKeeper / etcd 强一致性 Raft 协议保证；对于普通高并发幂等控制，单主加从集群的 Redis 分布式锁足以满足需求。

---

## 四、集群主从切换与脑裂故障排查

### 4.1 脑裂 (Split-Brain) 现象与防护
- **现象**: Master 节点因网络抖动与 Sentinel/Cluster 失去心跳，Sentinel 选举出新 Master；但旧 Master 仍可接收部分客户端写入，网络恢复后旧 Master 降级为 Slave，期间写入的数据**永久丢失**。
- **核心防护参数配置**:
  ```conf
  # 至少有 1 个从节点保持心跳延迟小于等于 10 秒，否则 Master 拒绝客户端写入
  min-replicas-to-write 1
  min-replicas-max-lag 10
  ```
