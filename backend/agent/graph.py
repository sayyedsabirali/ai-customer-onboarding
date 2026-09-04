from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

from agent.state import AgentState
from agent.nodes import (
    greeting_node,
    collect_info_node,
    validate_info_node,
    document_collection_node,
    document_validation_node,
    api_trigger_node,
    escalation_check_node,
    completion_node,
    route_after_greeting,
    route_after_collect_info,
    route_after_validate_info,
    route_after_document_collection,
    route_after_document_validation,
    route_after_api_trigger,
    route_after_escalation
)
from database.connection import DATABASE_URL


def build_onboarding_graph(checkpointer: AsyncPostgresSaver) -> StateGraph:
    """
    Build the LangGraph state graph with provided checkpointer.
    """
    workflow = StateGraph(AgentState)
    
    # ===== Add Nodes =====
    workflow.add_node("greeting", greeting_node)
    workflow.add_node("collect_info", collect_info_node)
    workflow.add_node("validate_info", validate_info_node)
    workflow.add_node("collect_docs", document_collection_node)
    workflow.add_node("validate_docs", document_validation_node)
    workflow.add_node("api_trigger", api_trigger_node)
    workflow.add_node("escalation", escalation_check_node)
    workflow.add_node("completion", completion_node)
    
    # ===== Set Entry Point =====
    workflow.set_entry_point("greeting")
    
    # ===== Add Edges =====
    workflow.add_edge("greeting", "collect_info")
    
    workflow.add_conditional_edges(
        "collect_info",
        route_after_collect_info,
        {
            "collect_info": "collect_info",
            "validate_info": "validate_info",
            "collect_docs": "collect_docs"
        }
    )
    
    workflow.add_conditional_edges(
        "validate_info",
        route_after_validate_info,
        {
            "collect_info": "collect_info",
            "collect_docs": "collect_docs"
        }
    )
    
    workflow.add_conditional_edges(
        "collect_docs",
        route_after_document_collection,
        {
            "collect_docs": "collect_docs",
            "validate_docs": "validate_docs"
        }
    )
    
    workflow.add_conditional_edges(
        "validate_docs",
        route_after_document_validation,
        {
            "collect_docs": "collect_docs",
            "api_trigger": "api_trigger",
            "end": END
        }
    )
    
    workflow.add_conditional_edges(
        "api_trigger",
        route_after_api_trigger,
        {
            "escalation": "escalation",
            "completion": "completion"
        }
    )
    
    workflow.add_conditional_edges(
        "escalation",
        route_after_escalation,
        {
            "end": END
        }
    )
    
    workflow.add_edge("completion", END)
    
    return workflow.compile(checkpointer=checkpointer)