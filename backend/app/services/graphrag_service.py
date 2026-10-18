"""
GraphRAG 知识图谱引擎与技能拓扑推理服务
研发单位：辽宁大学 · 辽宁省公共舆情与网络安全信息系统重点实验室
核心职责：
1. 构建技术技能、底层原理、工程场景与经典真题的多维实体关系图谱 (Knowledge Graph)
2. 支持子图多跳检索 (Multi-hop Subgraph Traversal) 与拓扑追问链生成
3. 将图谱结构化三元组增强注入大模型上下文 (Graph-augmented Context Generation)
"""

import logging
from typing import List, Dict, Any, Optional, Set
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class GraphEntity(BaseModel):
    """图谱实体节点"""
    id: str = Field(description="实体全局唯一标识")
    name: str = Field(description="实体名称")
    type: str = Field(description="实体类型: skill, concept, scenario, question")
    category: str = Field(default="general", description="技术类别: language, framework, database, rag, agent")
    description: str = Field(default="", description="实体背景释义与考察核心")
    level: int = Field(default=1, description="难度层级: 1-基础, 2-机制与踩坑, 3-高并发与底层")


class GraphRelation(BaseModel):
    """图谱关系边 (三元组: source -> relation -> target)"""
    source: str = Field(description="起始实体 ID")
    target: str = Field(description="目标实体 ID")
    type: str = Field(description="关系类型: DEPENDS_ON, EXAMINES, MITIGATES, APPLIED_TO")
    description: str = Field(default="", description="关系语义描述")


class SubgraphResult(BaseModel):
    """子图检索结果"""
    seed_entities: List[str] = Field(description="命中查询的种子实体")
    nodes: List[GraphEntity] = Field(description="子图节点集合")
    edges: List[GraphRelation] = Field(description="子图关系边集合")
    traversal_paths: List[str] = Field(description="拓扑递进路径链")
    graph_context: str = Field(description="注入 LLM 的自然语言图谱结构化上下文")


class GraphRAGService:
    """企业级 GraphRAG 图谱检索与推理引擎"""

    def __init__(self):
        self._nodes: Dict[str, GraphEntity] = {}
        self._adj: Dict[str, List[GraphRelation]] = {}  # 出边邻接表
        self._rev_adj: Dict[str, List[GraphRelation]] = {}  # 入边邻接表
        self._init_domain_knowledge_graph()

    def _init_domain_knowledge_graph(self):
        """初始化真实的高校就业技术栈与面试真题图谱"""
        # 1. 实体定义
        entities = [
            # Python / FastAPI / 异步高并发
            GraphEntity(id="python_async", name="Python asyncio 协程与事件循环", type="concept", category="language", level=1, description="单线程事件循环调度与非阻塞协程机制"),
            GraphEntity(id="fastapi_asgi", name="FastAPI & ASGI 异步微服务架构", type="skill", category="framework", level=2, description="基于 Uvicorn/Starlette 的异步请求生命周期与上下文管理"),
            GraphEntity(id="db_pool_tuning", name="SQLAlchemy / 连接池调优", type="concept", category="framework", level=2, description="pool_size, max_overflow 避免突发并发下连接泄露"),
            GraphEntity(id="concurrency_1000qps", name="1000+ QPS 极限高并发压测与调优", type="scenario", category="architecture", level=3, description="高并发请求下数据库连接池被打爆与 CPU 上下文切换瓶颈"),

            # Redis 缓存与锁
            GraphEntity(id="redis_basics", name="Redis 内存数据结构", type="skill", category="database", level=1, description="String, Hash, List, Set, ZSet 核心命令与时间复杂度"),
            GraphEntity(id="cache_breakdown", name="缓存穿透/击穿/雪崩治理", type="concept", category="database", level=2, description="布隆过滤器、互斥锁与随机过期时间兜底设计"),
            GraphEntity(id="redis_lua_limiter", name="Redis ZSet + Lua 原子滑动窗口限流", type="skill", category="architecture", level=3, description="多实例集群下保证时间窗口清理与计数写入的绝对原子性"),
            GraphEntity(id="redlock_distributed", name="Redlock 分布式锁与看门狗", type="concept", category="database", level=3, description="锁超期防误删、Lua 脚本释放、多节点时钟飘移一致性"),

            # RAG / 检索增强
            GraphEntity(id="vector_embedding", name="Dense 向量语义表征与 HNSW", type="concept", category="rag", level=1, description="BGE 向量检索与欧氏/余弦相似度计算"),
            GraphEntity(id="pg_gin_inverted", name="PostgreSQL GIN 倒排索引与 tsvector", type="skill", category="database", level=2, description="原生大厂规格全文关键词检索与精准词法召回"),
            GraphEntity(id="rrf_hybrid_fusion", name="加权 RRF 混合检索双路融合", type="concept", category="rag", level=2, description="Reciprocal Rank Fusion 无量纲倒数排名平滑融合"),
            GraphEntity(id="cross_encoder_rerank", name="Cross-Encoder 重排器长尾抑制", type="concept", category="rag", level=3, description="BGE-Reranker 全局交互注意力对 Top-N 候选重打分"),
            GraphEntity(id="corrective_rag", name="Corrective RAG (CRAG) 查询重写与自愈", type="scenario", category="rag", level=3, description="检索评估器置信度低时自动触发 Query 改写与二次召回"),

            # Agent / 智能体
            GraphEntity(id="react_framework", name="ReAct 模式 (Thought-Action-Observation)", type="concept", category="agent", level=1, description="单智能体反思与工具调用循环"),
            GraphEntity(id="langgraph_state_machine", name="LangGraph 分层有限状态机", type="skill", category="agent", level=2, description="节点条件分支路由与复杂任务宏微观状态解耦"),
            GraphEntity(id="checkpointer_rollback", name="Checkpointer 快照与死循环熔断", type="concept", category="agent", level=3, description="状态哈希检测重复路径，触发安全熔断与局部回滚"),
            GraphEntity(id="hitl_human_loop", name="HITL (Human-in-the-Loop) 人机断点协同", type="scenario", category="agent", level=3, description="敏感操作中断挂起，等待人工审核确认后状态无缝恢复")
        ]

        for e in entities:
            self._nodes[e.id] = e
            self._adj[e.id] = []
            self._rev_adj[e.id] = []

        # 2. 关系三元组定义
        relations = [
            # Python 异步链路
            GraphRelation(source="python_async", target="fastapi_asgi", type="DEPENDS_ON", description="FastAPI 的原生异步特性建立在 Python asyncio 之上"),
            GraphRelation(source="fastapi_asgi", target="db_pool_tuning", type="APPLIED_TO", description="异步框架调用数据库需配合连接池防止连接打满"),
            GraphRelation(source="db_pool_tuning", target="concurrency_1000qps", type="EXAMINES", description="1000+ QPS 压测核心考察连接池调优与协程阻塞预防"),

            # Redis 链路
            GraphRelation(source="redis_basics", target="cache_breakdown", type="APPLIED_TO", description="利用基础数据结构解决缓存三害问题"),
            GraphRelation(source="cache_breakdown", target="redis_lua_limiter", type="DEPENDS_ON", description="防止高并发突发击穿数据库的核心手段是限流防刷"),
            GraphRelation(source="redis_lua_limiter", target="redlock_distributed", type="EXAMINES", description="考察高并发一致性从 Lua 原子脚本进阶到分布式锁"),

            # RAG 混合检索链路
            GraphRelation(source="vector_embedding", target="rrf_hybrid_fusion", type="APPLIED_TO", description="向量语义作为 RRF 融合通道之一"),
            GraphRelation(source="pg_gin_inverted", target="rrf_hybrid_fusion", type="APPLIED_TO", description="PG 原生倒排提供精准词频召回，弥补向量局限"),
            GraphRelation(source="rrf_hybrid_fusion", target="cross_encoder_rerank", type="DEPENDS_ON", description="融合后的候选集由重排器进行二次精排打分"),
            GraphRelation(source="cross_encoder_rerank", target="corrective_rag", type="EXAMINES", description="评估重排分数过低时，自愈触发 CRAG 重检索"),

            # Agent 智能体链路
            GraphRelation(source="react_framework", target="langgraph_state_machine", type="DEPENDS_ON", description="复杂业务从线性 ReAct 升级为拓扑状态机"),
            GraphRelation(source="langgraph_state_machine", target="checkpointer_rollback", type="APPLIED_TO", description="状态机节点间利用快照记录历史状态支持回滚"),
            GraphRelation(source="checkpointer_rollback", target="hitl_human_loop", type="EXAMINES", description="熔断或高危动作阻断后，流转至人工断点恢复")
        ]

        for r in relations:
            self._adj[r.source].append(r)
            self._rev_adj[r.target].append(r)

    def search_subgraph(self, query_text: str, max_depth: int = 2) -> SubgraphResult:
        """
        基于实体链接与图多跳遍历执行 GraphRAG 检索
        """
        query_lower = query_text.lower()
        matched_seeds: List[str] = []

        # 1. 种子实体识别 (Entity Linking)
        for node_id, node in self._nodes.items():
            if (node_id.lower() in query_lower or
                node.name.lower() in query_lower or
                any(token in query_lower for token in node.name.lower().split())):
                matched_seeds.append(node_id)

        # 启发式兜底：根据常用关键词匹配
        if not matched_seeds:
            if any(k in query_lower for k in ["redis", "缓存", "限流", "lua", "锁"]):
                matched_seeds = ["redis_lua_limiter"]
            elif any(k in query_lower for k in ["fastapi", "异步", "并发", "qps", "python"]):
                matched_seeds = ["fastapi_asgi"]
            elif any(k in query_lower for k in ["rag", "bm25", "向量", "召回", "重排", "rrf"]):
                matched_seeds = ["rrf_hybrid_fusion"]
            elif any(k in query_lower for k in ["agent", "状态机", "langgraph", "熔断", "快照"]):
                matched_seeds = ["langgraph_state_machine"]
            else:
                matched_seeds = ["python_async", "redis_basics"]

        # 2. 多跳子图遍历 (Multi-hop BFS)
        visited_nodes: Set[str] = set(matched_seeds)
        result_edges: List[GraphRelation] = []
        traversal_paths: List[str] = []

        queue = [(seed, 0, [self._nodes[seed].name]) for seed in matched_seeds]

        while queue:
            curr_id, depth, path = queue.pop(0)
            if depth >= max_depth:
                traversal_paths.append(" -> ".join(path))
                continue

            # 遍历出边
            for edge in self._adj.get(curr_id, []):
                result_edges.append(edge)
                target_node = self._nodes.get(edge.target)
                if edge.target not in visited_nodes and target_node:
                    visited_nodes.add(edge.target)
                    queue.append((edge.target, depth + 1, path + [f"[{edge.type}]", target_node.name]))
                else:
                    if target_node:
                        traversal_paths.append(" -> ".join(path + [f"[{edge.type}]", target_node.name]))

        # 3. 构建注入大模型的自然语言结构化图谱上下文 (Graph Context)
        node_objs = [self._nodes[nid] for nid in visited_nodes if nid in self._nodes]
        context_lines = [
            "【GraphRAG 技能拓扑与核心考点上下文】:",
            f"1. 核心种子技能: {', '.join(self._nodes[s].name for s in matched_seeds if s in self._nodes)}",
            "2. 关联技术实体与考察要求:"
        ]
        for n in node_objs:
            context_lines.append(f"   • [{n.name}] (等级 L{n.level}): {n.description}")

        context_lines.append("3. 技术依赖与递进考法链路 (Graph Traversal Paths):")
        for p in traversal_paths[:4]:
            context_lines.append(f"   ↳ {p}")

        graph_context_str = "\n".join(context_lines)

        return SubgraphResult(
            seed_entities=matched_seeds,
            nodes=node_objs,
            edges=result_edges,
            traversal_paths=traversal_paths,
            graph_context=graph_context_str
        )

    def get_full_graph(self) -> Dict[str, Any]:
        """返回全图数据供前端可视化展示"""
        return {
            "nodes": [n.dict() for n in self._nodes.values()],
            "edges": [e.dict() for edges in self._adj.values() for e in edges]
        }


# 全局单例
graphrag_service = GraphRAGService()
