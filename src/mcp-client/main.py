import os
import yaml
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Response

from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from typing import Optional

from models import IntentRequest, IntentResult
from agent import NetworkAgent
from pydantic import BaseModel
from hitl.models import ApprovalStatus
from observability.middleware import ObservabilityMiddleware
from observability.tracing import tracing
from observability.metrics import metrics
from observability.logging import logger as structured_logger

class ApproveRequest(BaseModel):
    request_id: str
    reason: Optional[str] = None

class RejectRequest(BaseModel):
    request_id: str
    reason: str

# Загрузка конфигурации.
def load_config():
    config_path = os.getenv("CONFIG_PATH", "config.yaml")
    try:
        with open(config_path, "r") as f:
            logger.info(f"Load config from file: {config_path}")
            return yaml.safe_load(f)
    except FileNotFoundError:
        logger.warning(f"Config {config_path} not found, using env")
        return {}
    except Exception as e:
        logger.error(f"Error while loading config: {e}")
        return {}

config = load_config()

tracing.initialize()

agent = NetworkAgent(config)


@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    logger.info("Startup FastAPI app and init MCP Network Agent...")
    try:
        if 'tracing' in globals():
            tracing.initialize()
            tracing.instrument_fastapi(fastapi_app)
            tracing.instrument_httpx()

        await agent.initialize()

        # Первичное наполнение стартовых метрик Prometheus.
        if agent.rag_manager:
            info = agent.rag_manager.get_collection_info()
            metrics.update_rag_collection_size(info.get('count', 0))
        
        metrics.update_mcp_servers(1 if agent.mcp_client else 0)
        logger.info("Agent connected to C# MCP server and ready")
    except Exception as e:
        logger.error(f"Critical error while init: {e}")
        raise SystemExit("Сбой запуска сервиса из-за ошибки инициализации агента")

    yield

    logger.info("Stopping FastAPI app. Release resources...")
    await agent.close()
    logger.info("All MCP sessions and sockets are closed")


app = FastAPI(
    title="MCP Network Agent",
    description="Программа для управления конфигурациями сети с MCP",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(ObservabilityMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if tracing.is_enabled():
    try:
        tracing.instrument_fastapi(app)
        tracing.instrument_httpx()
        logger.info("OpenTelemetry is enabled")
    except Exception as e:
        logger.warning(f"Instrument error: {e}")
else:
    logger.info("OpenTelemetry is NOT enabled")

@app.get("/")
async def root():
    return {
        "service": "MCP Network Agent API",
        "status": "running",
        "tools": list(agent.mcp_client.tools.keys()) if agent.mcp_client else []
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy", 
        "initialized": agent._initialized,
        "tools_count": len(agent.mcp_client.tools) if agent.mcp_client else 0
    }

@app.get("/metrics")
async def metrics_endpoint():
    return Response(
        content=metrics.get_metrics(),
        media_type="text/plain; version=0.0.4; charset=utf-8"
    )

@app.post("/intent", response_model=IntentResult)
async def process_intent(request: IntentRequest):
    """
    Обрабатывает намерение пользователя.
    """
    logger.info(f"Receive intent from API: '{request.text}' (Project: {request.project_id})")

    try:
        result = await agent.process_intent(
            intent_text=request.text,
            project_id=request.project_id
        )
        
        if result.get("status") == "error":
            logger.warning(f"The agent failed to complete the task: {result.get('error')}")
            raise HTTPException(status_code=422, detail=result.get("error"))

        return IntentResult(**result)
        
    except HTTPException:
        raise
    except Exception as e:
        metrics.record_error("unhandled_intent_processing_crash")
        logger.error(f"Unexpected error while processing the intent: {e}")
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка ИИ агента: {str(e)}")


@app.get("/tools")
async def list_tools():
    """Возвращает список доступных MCP инструментов"""
    if not agent.mcp_client:
        return {"tools": []}
    
    return {
        "tools": [
            {
                "name": name,
                "description": tool.description,
                "schema": tool.input_schema if hasattr(tool, 'input_schema') else {}
            }
            for name, tool in agent.mcp_client.tools.items()
        ]
    }


@app.get("/hitl/pending")
async def get_pending_approvals():
    """Возвращает список сценариев, ожидающих ручного подтверждения"""
    if not agent.hitl_enabled:
        raise HTTPException(status_code=400, detail="Human-in-the-Loop отключен")

    pending = agent.hitl_manager.get_pending_requests()
    
    metrics.update_pending_approvals(len(pending))
    
    return {
        "pending": pending,
        "count": len(agent.hitl_manager._pending_requests)
    }


@app.post("/hitl/approve")
async def approve_request(request: ApproveRequest):
    """Утверждает сценарий и запускает деплой"""
    if not agent.hitl_enabled:
        raise HTTPException(status_code=400, detail="Human-in-the-Loop отключен")
    
    logger.info(f"API: APPROVE command received for session ID: {request.request_id}")
    
    response = await agent.hitl_manager.approve_request(
        request_id=request.request_id,
        approver="api_operator"
    )

    metrics.record_approval(status="approved", priority=getattr(response, "priority", "medium"))

    return {
        "status": "success",
        "request_id": request.request_id,
        "response": response.model_dump()
    }


@app.post("/hitl/reject")
async def reject_request(request: RejectRequest):
    """Отклоняет ИИ изменения, блокируя их применение"""
    if not agent.hitl_enabled:
        raise HTTPException(status_code=400, detail="Human-in-the-Loop отключен")
    
    logger.warning(f"API: REJECT command received for session ID: {request.request_id}. Причина: {request.reason}")
    
    response = await agent.hitl_manager.reject_request(
        request_id=request.request_id,
        reason=request.reason
    )

    metrics.record_approval(status="rejected", priority=getattr(response, "priority", "medium"))
    
    return {
        "status": "success",
        "request_id": request.request_id,
        "response": response.model_dump()
    }


@app.get("/hitl/status/{request_id}")
async def get_approval_status(request_id: str):
    """Возвращает статус и метаданные сессии утверждения по её ID"""
    if not agent.hitl_enabled:
        raise HTTPException(status_code=400, detail="Human-in-the-Loop отключен")
    
    status = agent.hitl_manager.get_status(request_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"Запрос с ID {request_id} не найден")
    
    request = agent.hitl_manager.get_request(request_id)
    
    status_value = status.value if hasattr(status, 'value') else str(status)
    
    return {
        "request_id": request_id,
        "status": status_value,
        "request": request.model_dump() if request else None
    }


if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    is_dev = os.getenv("ENV", "production").lower() == "development"
    
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=is_dev,
        log_level="info"
    )
