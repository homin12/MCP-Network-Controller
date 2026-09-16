import json
import sys
from typing import Dict, Any, Optional
from datetime import datetime
from loguru import logger as loguru_logger
from loguru._defaults import LOGURU_FORMAT
import os

class StructuredLogger:
    """
    Реализует структурированное логирование и сквозную трассировку.
    """
    def __init__(self, env: str = "production", logs_dir: str = "logs"):
        self.logs_dir = logs_dir
        os.makedirs(logs_dir, exist_ok=True)
        
        loguru_logger.remove()
        
        if env.lower() == "development":
            loguru_logger.add(
                sys.stdout,
                format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level> <blue>{extra}</blue>",
                level="DEBUG"
            )
        else:
            loguru_logger.add(
                sys.stdout,
                serialize=True,
                level="INFO"
            )
        
        loguru_logger.add(
            os.path.join(logs_dir, "agent_{time:YYYY-MM-DD}.jsonl"),
            serialize=True,
            rotation="1 day",
            retention="30 days",
            level="INFO"
        )
        
        loguru_logger.add(
            os.path.join(logs_dir, "agent_debug.log"),
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message} {extra}",
            rotation="10 MB",
            retention="7 days",
            level="DEBUG"
        )
        
        self._base_logger = loguru_logger

    def bind(self, **kwargs) -> Any:
        return self._base_logger.bind(**kwargs)

    def debug(self, message: str, **kwargs):
        self._base_logger.bind(**kwargs).debug(message)
        
    def info(self, message: str, **kwargs):
        self._base_logger.bind(**kwargs).info(message)
        
    def warning(self, message: str, **kwargs):
        self._base_logger.bind(**kwargs).warning(message)
        
    def error(self, message: str, **kwargs):
        self._base_logger.bind(**kwargs).error(message)
        
    def critical(self, message: str, **kwargs):
        self._base_logger.bind(**kwargs).critical(message)
        
    def exception(self, message: str, **kwargs):
        self._base_logger.bind(**kwargs).exception(message)

    def log_request(self, request_id: str, intent: str, **kwargs):
        """Регистрирует входящую бизнес-задачу."""
        self._base_logger.bind(
            event_type="request",
            request_id=request_id,
            intent=intent[:500]
        ).info(f"Received user intent: '{intent[:60]}...'")
    
    def log_analysis(self, request_id: str, action_type: str, commands_count: int, **kwargs):
        """Регистрирует результаты работы ИИ."""
        self._base_logger.bind(
            event_type="analysis",
            request_id=request_id,
            action_type=action_type,
            commands_count=commands_count,
            **kwargs
        ).info(f"LLM Analysis completed. Action: {action_type} ({commands_count} cmds generated)")
    
    def log_validation(self, request_id: str, passed: bool, issues_count: int, **kwargs):
        """Регистрирует результаты прогона Batfish."""
        status = "PASSED" if passed else "FAILED"
        self._base_logger.bind(
            event_type="validation",
            request_id=request_id,
            passed=passed,
            issues_count=issues_count,
            **kwargs
        ).info(f"Digital Twin simulation: {status} ({issues_count} syntax/routing issues detected)")
    
    def log_approval(self, request_id: str, status: str, **kwargs):
        """Регистрирует решение HITL."""
        self._base_logger.bind(
            event_type="approval",
            request_id=request_id,
            hitl_status=status,
            **kwargs
        ).info(f"Human-in-the-Loop decision: {status.upper()}")
    
    def log_mcp_call(self, tool_name: str, success: bool, duration: float, **kwargs):
        """Регистрирует телеметрию вызовов MCP."""
        status = "success" if success else "failed"
        self._base_logger.bind(
            event_type="mcp_call",
            tool_name=tool_name,
            success=success,
            duration_ms=int(duration * 1000),
            **kwargs
        ).debug(f"MCP Call [{tool_name}] executed with status '{status}' in {duration:.3f}s")
    
    def log_rag_query(self, query: str, hits: int, confidence: float, **kwargs):
        """Регистрирует метрики извлечения данных из ChromaDB."""
        self._base_logger.bind(
            event_type="rag_retrieve",
            rag_query=query[:100],
            hits_count=hits,
            rag_confidence=confidence,
            **kwargs
        ).debug(f"RAG Extracted {hits} docs for query (Confidence: {confidence:.2f})")


# Инициализируем глобальный синглтон.
env_type = os.getenv("ENV", "production")
logger = StructuredLogger(env=env_type)