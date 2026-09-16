import os
from typing import Dict, Any, Optional, Callable
from functools import wraps
from loguru import logger

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.trace import Span, Status, StatusCode
from opentelemetry.semconv.resource import ResourceAttributes
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor


class TracingManager:
    """
    Управляет OpenTelemetry.
    """
    
    def __init__(self, service_name: str = "mcp-agent", 
                 otlp_endpoint: Optional[str] = None,
                 enabled: bool = True):
        self.service_name = service_name
        self.otlp_endpoint = otlp_endpoint or os.getenv("OTLP_ENDPOINT", "")
        self.enabled = enabled and bool(self.otlp_endpoint)
        self._initialized = False
        self._tracer: Optional[trace.Tracer] = None
    
    def initialize(self):
        """Инициализирует трассировку."""
        if self._initialized:
            return
        
        if not self.enabled:
            logger.info("OpenTelemetry tracing is disabled.")
            self._initialized = True
            return
        
        try:
            resource = Resource.create({
                ResourceAttributes.SERVICE_NAME: self.service_name,
                ResourceAttributes.DEPLOYMENT_ENVIRONMENT: os.getenv("ENVIRONMENT", "development"),
            })
            
            provider = TracerProvider(resource=resource)
            
            exporter_added = False
            
            if self.otlp_endpoint:
                try:
                    exporter = OTLPSpanExporter(endpoint=self.otlp_endpoint, insecure=True)
                    provider.add_span_processor(BatchSpanProcessor(exporter))
                    exporter_added = True
                    logger.info(f"OTLP exporter added: {self.otlp_endpoint}")
                except Exception as e:
                    logger.warning(f"Failed to connect to OTLP: {e}")
            
            if os.getenv("ENVIRONMENT") != "production":
                provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
                logger.info("Debugging Console exporter added.")
            
            if not exporter_added:
                provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
                logger.info("OTLP is unavailable; only the console exporter is used.")
            
            trace.set_tracer_provider(provider)
            
            self._tracer = trace.get_tracer(self.service_name)
            self._initialized = True
            
            logger.info("OpenTelemetry init")
            
        except Exception as e:
            logger.warning(f"Trace initialization error: {e}")
            self.enabled = False
            self._initialized = True
    
    def is_enabled(self) -> bool:
        """Проверяет, включена ли трассировка."""
        if not self._initialized:
            self.initialize()
        return self.enabled and self._tracer is not None
    
    def get_tracer(self) -> Optional[trace.Tracer]:
        """Возвращает tracer."""
        if not self._initialized:
            self.initialize()
        
        if not self.enabled:
            return None
        
        return self._tracer
    
    def create_span(self, name: str, attributes: Dict[str, Any] = None) -> Optional[Span]:
        """Создаёт новый span."""
        if not self.is_enabled():
            return None
        
        tracer = self.get_tracer()
        if tracer:
            return tracer.start_span(name, attributes=attributes)
        return None
    
    def instrument_fastapi(self, app):
        """Инструментирует FastAPI приложение."""
        if self.is_enabled():
            try:
                FastAPIInstrumentor.instrument_app(app, tracer_provider=trace.get_tracer_provider())
                logger.info("FastAPI is instrumented.")
            except Exception as e:
                logger.warning(f"FastAPI instrumentation error: {e}")
    
    def instrument_httpx(self):
        """Инструментирует HTTPX клиент"""
        if self.is_enabled():
            try:
                HTTPXClientInstrumentor().instrument()
                logger.info("HTTPX is instrumented.")
            except Exception as e:
                logger.warning(f"HTTPX instrumentation error: {e}")
    
    def trace_async(self, name: str, attributes: Dict[str, Any] = None):
        """
        Декоратор для асинхронных функций с трассировкой.
        """
        def decorator(func: Callable):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                if not self.is_enabled():
                    return await func(*args, **kwargs)
                
                tracer = self.get_tracer()
                if not tracer:
                    return await func(*args, **kwargs)
                
                with tracer.start_as_current_span(name, attributes=attributes) as span:
                    try:
                        result = await func(*args, **kwargs)
                        if span:
                            span.set_status(Status(StatusCode.OK))
                        return result
                    except Exception as e:
                        if span:
                            span.set_status(Status(StatusCode.ERROR, str(e)))
                            span.record_exception(e)
                        raise
            return wrapper
        return decorator
    
    def trace_sync(self, name: str, attributes: Dict[str, Any] = None):
        """
        Декоратор для синхронных функций с трассировкой.
        """
        def decorator(func: Callable):
            @wraps(func)
            def wrapper(*args, **kwargs):
                if not self.is_enabled():
                    return func(*args, **kwargs)
                
                tracer = self.get_tracer()
                if not tracer:
                    return func(*args, **kwargs)
                
                with tracer.start_as_current_span(name, attributes=attributes) as span:
                    try:
                        result = func(*args, **kwargs)
                        if span:
                            span.set_status(Status(StatusCode.OK))
                        return result
                    except Exception as e:
                        if span:
                            span.set_status(Status(StatusCode.ERROR, str(e)))
                            span.record_exception(e)
                        raise
            return wrapper
        return decorator


# Глобальный экземпляр с настройками из окружения.
tracing = TracingManager(
    service_name=os.getenv("OTEL_SERVICE_NAME", "mcp-agent"),
    otlp_endpoint=os.getenv("OTLP_ENDPOINT", ""),
    enabled=os.getenv("OTEL_ENABLED", "true").lower() == "true"
)