import pytest
from app.services.agent_workflow import AgentWorkflow, AgentState
from app.core.circuit_breaker import CircuitBreaker, CircuitState


def test_agent_intent_routing_logic():
    """测试意图分类与分流决策节点"""
    wf = AgentWorkflow()

    # 1. 纯闲聊/问候 -> 走 direct_chat
    state_chat: AgentState = {
        "messages": [{"role": "user", "content": "你好，今天辛苦了！"}],
        "kb_ids": ["kb_sre_enterprise"],
        "intent": "direct_chat",
        "loop_count": 0,
        "citations": [],
    }
    route = wf.route_based_on_intent(state_chat)
    assert route == "direct_chat"

    # 2. 技术故障排查 -> 走 need_retrieval
    state_sop: AgentState = {
        "messages": [{"role": "user", "content": "Kubernetes OOMKilled 怎么排查？"}],
        "kb_ids": ["kb_sre_enterprise"],
        "intent": "need_retrieval",
        "loop_count": 0,
        "citations": [],
    }
    route_sop = wf.route_based_on_intent(state_sop)
    assert route_sop == "need_retrieval"


def test_agent_loop_prevention_circuit_breaker():
    """测试 Agent 反思重试的最大循环阈值熔断机制 (防死循环空转)"""
    wf = AgentWorkflow()

    # 循环次数达到上限
    state_loop_overflow: AgentState = {
        "messages": [{"role": "user", "content": "反复查询未命中文档"}],
        "kb_ids": ["kb_sre_enterprise"],
        "intent": "need_retrieval",
        "loop_count": 5,  # 超过 MAX_RETRIES (3)
        "citations": [],
    }
    decision = wf.should_continue(state_loop_overflow)
    # 熔断必须终止循环，强制走向结束
    assert decision == "end"


def test_circuit_breaker_core():
    """测试通用熔断器底层状态转换 (CLOSED -> OPEN)"""
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=5.0)
    assert cb.state == CircuitState.CLOSED

    # 记录 3 次异常失败
    dummy_err = RuntimeError("Upstream timeout")
    cb._record_failure(dummy_err)
    cb._record_failure(dummy_err)
    assert cb.state == CircuitState.CLOSED
    cb._record_failure(dummy_err)
    assert cb.state == CircuitState.OPEN
