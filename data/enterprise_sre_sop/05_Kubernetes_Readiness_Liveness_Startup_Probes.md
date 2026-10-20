# Kubernetes Readiness / Liveness / Startup 探针区别与生产配置 SOP

## 一、一句话结论

- **readinessProbe（就绪探针）**：判断 Pod 是否可以接收流量。失败时把 Pod 从 Service Endpoints 中摘除，**不重启容器**。
- **livenessProbe（存活探针）**：判断容器是否还活着。失败时 Kubelet 按 `restartPolicy` **重启容器**。
- **startupProbe（启动探针）**：判断应用是否启动完成。启动成功前，Kubelet 暂停 liveness/readiness；失败时按重启策略重启容器。

## 二、readinessProbe：决定“能不能接流量”

### 2.1 作用

readinessProbe 失败时，Kubelet 会把 Pod 标记为 `NotReady`，并从对应 Service 的 Endpoints/EndpointSlice 中移除。Pod 仍然在运行，不会被重启；探针恢复后会自动重新加入 Endpoints。

### 2.2 适用场景

- 应用启动后需要加载配置、预热缓存、建立连接池；
- 应用依赖的下游暂时不可用，但进程本身健康，希望暂时不接流量；
- 滚动更新时，确保新 Pod 真正可用后再切流量。

### 2.3 常见误区

- 在 readiness 中检查所有下游依赖（数据库、Redis、第三方 API）。下游抖动会导致全部 Pod 同时 NotReady，形成“自我熔断”。
- readiness 失败不会重启 Pod，所以不能用它来修复死锁或进程卡死；这类问题应该用 liveness。
- 没有 readiness 时，Pod 一启动就会被加入 Endpoints，可能把请求打到还没准备好的实例。

## 三、livenessProbe：决定“要不要重启”

### 3.1 作用

livenessProbe 连续失败达到 `failureThreshold` 后，Kubelet 会杀掉容器并按 `restartPolicy` 重启。重启次数会体现在 `kubectl describe pod` 的 `Restart Count` 和事件里。

### 3.2 适用场景

- 进程死锁、事件循环阻塞、goroutine/线程泄漏等“进程还在但已经不可用”的情况；
- 应用无法自行恢复，需要靠重启恢复。

### 3.3 常见误区

- **不要在 liveness 中检查数据库/Redis 等外部依赖**。下游故障会导致所有 Pod 同时重启，放大故障。
- liveness 的 `initialDelaySeconds` 不适合处理慢启动；慢启动应该用 startupProbe，否则应用还没启动完就被 liveness 杀掉，形成 CrashLoopBackOff。
- liveness 只应检查进程自身能否响应，例如本地 HTTP `/healthz` 或轻量 TCP 端口。

## 四、startupProbe：慢启动应用的保护伞

startupProbe 在成功之前会**禁用 liveness 和 readiness**。它适合启动时间较长（如加载大模型、预热大量数据）的应用。

- startupProbe 成功：恢复 liveness/readiness；
- startupProbe 失败：按 `restartPolicy` 重启容器；
- 配置上通常给较大的 `failureThreshold × periodSeconds`，例如 30 次 × 10 秒 = 5 分钟启动窗口。

## 五、三者对比

| 维度 | readinessProbe | livenessProbe | startupProbe |
| :--- | :--- | :--- | :--- |
| 判断目标 | 是否能接流量 | 容器是否存活 | 应用是否启动完成 |
| 失败行为 | 从 Service Endpoints 摘除 | 重启容器 | 重启容器 |
| 会重启容器吗 | 不会 | 会 | 会 |
| 会摘流量吗 | 会 | 通常也会（容器重启期间） | 启动期间不接流量 |
| 典型检查 | HTTP `/ready`、TCP 端口 | HTTP `/healthz`、exec 轻量命令 | 同 liveness，但允许更长启动时间 |
| 常见配置 | 依赖就绪、连接池预热 | 进程自身健康 | 慢启动/大模型加载 |

## 六、YAML 示例

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: api-server
spec:
  containers:
    - name: api
      image: example/api:1.0
      ports:
        - containerPort: 8080
      startupProbe:
        httpGet:
          path: /healthz
          port: 8080
        periodSeconds: 10
        failureThreshold: 30
      readinessProbe:
        httpGet:
          path: /ready
          port: 8080
        initialDelaySeconds: 5
        periodSeconds: 5
        timeoutSeconds: 2
        failureThreshold: 3
      livenessProbe:
        httpGet:
          path: /healthz
          port: 8080
        initialDelaySeconds: 10
        periodSeconds: 10
        timeoutSeconds: 2
        failureThreshold: 3
```

## 七、关键参数

- `initialDelaySeconds`：容器启动后等待多久开始探测；
- `periodSeconds`：探测间隔；
- `timeoutSeconds`：单次探测超时；
- `successThreshold`：连续成功多少次视为恢复（liveness 通常为 1）；
- `failureThreshold`：连续失败多少次触发动作。

## 八、排障路径

1. **Pod Running 但 Service 没有流量**：检查 readinessProbe 是否失败、Pod 是否在 Endpoints 中：
   ```bash
   kubectl get pod <pod> -n <ns> -o wide
   kubectl describe pod <pod> -n <ns> | grep -A5 -i readiness
   kubectl get endpoints <service> -n <ns>
   ```
2. **Pod 反复重启**：检查 livenessProbe 是否失败、Restart Count、容器退出码：
   ```bash
   kubectl describe pod <pod> -n <ns> | grep -E "Restart Count|Liveness|Events" -A3
   kubectl logs <pod> -n <ns> --previous
   ```
3. **慢启动应用 CrashLoopBackOff**：确认是否缺少 startupProbe，或 liveness 的 `initialDelaySeconds/failureThreshold` 太小。

## 九、生产建议

- liveness 只检查进程自身，不检查外部依赖；
- readiness 可以检查必要的本地状态；下游依赖检查要配合降级和超时，避免全量摘流量；
- 慢启动应用必须配 startupProbe，不要靠放大 liveness 的 `initialDelaySeconds`；
- 探针端点要轻量，避免在探针里做重查询、全表扫描或远程调用；
- 探针失败要有日志和告警，不能只看 Pod 状态。
