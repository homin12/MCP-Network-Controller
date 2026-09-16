import time
import uuid
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from .metrics import metrics
from .logging import logger as structured_logger
from .tracing import tracing
from opentelemetry.trace import StatusCode, Status


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """
    Middleware для сбора метрик Prometheus, логирования Loguru и трассировки OpenTelemetry.
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id
        
        path_parts = [p for p in request.url.path.split('/') if p]
        metric_type = path_parts[0] if path_parts else 'root'
        
        tracer = tracing.get_tracer() if tracing.is_enabled() else None
        
        metrics.start_request()
        
        try:
            if tracer:
                with tracer.start_as_current_span(
                    name=f"http_{request.method.lower()}_{metric_type}",
                    attributes={
                        "http.method": request.method,
                        "http.url": str(request.url),
                        "http.path": request.url.path,
                        "request.id": request_id
                    }
                ) as span:
                    
                    with structured_logger._base_logger.contextualize(request_id=request_id):
                        response = await call_next(request)
                    
                    if span:
                        span.set_attribute("http.status_code", response.status_code)
                        if response.status_code >= 400:
                            span.set_status(Status(StatusCode.ERROR))
                        else:
                            span.set_status(Status(StatusCode.OK))
            else:
                with structured_logger._base_logger.contextualize(request_id=request_id):
                    response = await call_next(request)
            
            duration = time.time() - start_time
            status_label = "success" if response.status_code < 400 else "error"
            
            metrics.record_request(
                action_type=metric_type,
                status=status_label,
                duration=duration
            )
            
            response.headers["X-Request-ID"] = request_id
            return response
            
        except Exception as e:
            duration = time.time() - start_time
            metrics.record_error("unhandled_fastapi_crash")
            
            metrics.record_request(
                action_type=metric_type,
                status="error",
                duration=duration
            )
            
            structured_logger.exception(
                f"Critical error in HTTP pipeline: {e}",
                request_id=request_id,
                error_type=e.__class__.__name__
            )
            
            if tracer:
                current_span = tracer.get_current_span()
                if current_span:
                    current_span.set_status(Status(StatusCode.ERROR, str(e)))
                    current_span.record_exception(e)
            
            raise
