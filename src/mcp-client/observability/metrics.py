from prometheus_client import Counter, Histogram, Gauge, Info, generate_latest, REGISTRY
from typing import Dict, Any
from loguru import logger


class MetricsCollector:
    """
    Сборщик телеметрических метрик для интеграции с Prometheus/Grafana.
    """
    
    def __init__(self):
        # Количество входящих запросов.
        self.requests_total = Counter(
            'agent_requests_total',
            'Total number of intent requests processed by the agent',
            ['action_type', 'status']
        )
        
        # Общее количество синтезированных ИИ CLI-команд.
        self.commands_generated_total = Counter(
            'agent_commands_generated_total',
            'Total number of Cisco IOS CLI commands synthesized by LLM',
            ['action_type']
        )
        
        # Статистика применения конфигураций.
        self.commands_applied_total = Counter(
            'agent_commands_applied_total',
            'Total number of CLI commands dispatched to devices via C# MCP',
            ['device', 'success']
        )
        
        # Метрики симулятора Batfish.
        self.validation_results_total = Counter(
            'agent_validation_results_total',
            'Total number of network simulations executed on Batfish Digital Twin',
            ['check_type', 'passed']
        )
        
        # Результаты контроля HITL.
        self.approvals_total = Counter(
            'agent_approvals_total',
            'Total number of Human-in-the-Loop decision outcomes',
            ['status', 'priority']
        )
        
        # Сводный счетчик системных или инфраструктурных сбоев.
        self.errors_total = Counter(
            'agent_errors_total',
            'Total number of system/infrastructure exceptions caught',
            ['error_type']
        )
        
        # Плотность семантических попаданий базы знаний RAG.
        self.rag_hits_total = Counter(
            'agent_rag_hits_total',
            'Total number of semantic extractions from ChromaDB vector index',
            ['confidence_level']
        )
        
        # Время сквозной обработки намерения пользователя.
        self.request_duration = Histogram(
            'agent_requests_duration_seconds',
            'End-to-end request processing latency in seconds',
            ['action_type'],
            buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0]
        )
        
        # Чистая скорость генерации токенов моделью.
        self.command_generation_duration = Histogram(
            'agent_command_generation_duration_seconds',
            'LLM token synthesis latency for configuration scripts',
            ['commands_range'],
            buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 45.0]
        )
        
        # Время сборки снимков и расчета таблиц маршрутизации Batfish.
        self.validation_duration = Histogram(
            'agent_validation_duration_seconds',
            'Network topology simulation latency on Batfish twin',
            ['snapshot_status'],
            buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0]
        )
        
        # Мгновенный счетчик параллельных сессий в рантайме агента.
        self.active_requests = Gauge(
            'agent_active_requests',
            'Number of concurrent active intent sessions currently in-flight'
        )
        
        # Количество замороженных задач, висящих в ожидании клика в HITL.
        self.pending_approvals = Gauge(
            'agent_pending_approvals',
            'Number of automated tasks currently stalled waiting for operator approval'
        )
        
        # Текущий объем проиндексированных документов в ChromaDB.
        self.rag_collection_size = Gauge(
            'agent_rag_collection_size',
            'Total number of text document chunks registered in vector store index'
        )
        
        # Количество живых каналов к MCP серверам управления конфигурациями.
        self.connected_mcp_servers = Gauge(
            'agent_connected_mcp_servers',
            'Number of active transport links to C# MCP servers'
        )
        
        # Мета-информация.
        self.version_info = Info('agent_version', 'System build infrastructure version info')
        self.version_info.info({
            'version': '1.0.0',
            'python_version': '3.11',
            'mcp_protocol_spec': '2024-11-05',
            'digital_twin_engine': 'Batfish/Java'
        })
        
    def start_request(self):
        self.active_requests.inc()
    
    def record_request(self, action_type: str, status: str, duration: float):
        self.requests_total.labels(action_type=action_type, status=status).inc()
        self.request_duration.labels(action_type=action_type).observe(duration)
        self.active_requests.dec()
    
    def record_commands_generated(self, count: int, action_type: str, duration: float):
        self.commands_generated_total.labels(action_type=action_type).inc(count)
        
        range_label = "1-3" if count <= 3 else "4-10" if count <= 10 else "10+"
        self.command_generation_duration.labels(commands_range=range_label).observe(duration)
    
    def record_commands_applied(self, device: str, success: bool):
        self.commands_applied_total.labels(device=device, success=str(success)).inc()
    
    def record_validation(self, check_type: str, passed: bool, duration: float):
        status_str = "passed" if passed else "failed"
        self.validation_results_total.labels(check_type=check_type, passed=status_str).inc()
        self.validation_duration.labels(snapshot_status=status_str).observe(duration)
    
    def record_approval(self, status: str, priority: str):
        self.approvals_total.labels(status=status, priority=priority).inc()
    
    def record_error(self, error_type: str):
        self.errors_total.labels(error_type=error_type).inc()
    
    def record_rag_hit(self, confidence: float):
        level = "high" if confidence >= 0.7 else "medium" if confidence >= 0.4 else "low"
        self.rag_hits_total.labels(confidence_level=level).inc()
    
    def update_pending_approvals(self, count: int):
        self.pending_approvals.set(count)
    
    def update_rag_collection_size(self, size: int):
        self.rag_collection_size.set(size)
    
    def update_mcp_servers(self, count: int):
        self.connected_mcp_servers.set(count)
    
    def get_metrics(self) -> bytes:
        return generate_latest()

# Инициализируем синглтон модуля метрик.
metrics = MetricsCollector()