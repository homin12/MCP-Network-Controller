from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum

class DeviceCommand(BaseModel):
    """Команда для сетевого устройства."""
    device: str = Field(..., description="Имя устройства (например, R1)")
    cli: str = Field(..., description="Команда CLI для выполнения")


class CommandResult(BaseModel):
    """Результат выполнения команды."""
    device: str = Field(..., description="Имя устройства")
    command: str = Field(..., description="Выполненная команда")
    success: bool = Field(..., description="Успешно ли выполнена")
    output: Optional[str] = Field(None, description="Вывод команды")
    error: Optional[str] = Field(None, description="Сообщение об ошибке")


class DeviceInfo(BaseModel):
    """Информация об устройстве."""
    name: str = Field(..., description="Имя устройства")
    type: str = Field(..., description="Тип устройства")
    status: str = Field(..., description="Статус устройства")
    console: Optional[int] = Field(None, description="Номер консоли")


class IntentRequest(BaseModel):
    """Запрос на обработку намерения."""
    text: str = Field(..., description="Текст намерения на естественном языке")
    project_id: Optional[str] = Field(None, description="ID проекта")


class IntentResult(BaseModel):
    """Результат обработки намерения."""
    status: str = Field(..., description="Статус: success / error")
    intent: str = Field(..., description="Исходный текст намерения")
    project_id: str = Field(..., description="ID проекта")
    message: Optional[str] = Field(None, description="Сообщение для пользователя")
    devices: Optional[List[DeviceInfo]] = Field(None, description="Список устройств (для информационных запросов)")
    commands: Optional[List[DeviceCommand]] = Field(None, description="Сгенерированные команды")
    apply_result: Optional[Dict[str, Any]] = Field(None, description="Результат применения")
    inventory: Optional[Dict[str, Any]] = Field(None, description="Полный инвентарь")
    is_informational: Optional[bool] = Field(False, description="Является ли ответ информационным")
    error: Optional[str] = Field(None, description="Сообщение об ошибке")


class InventoryResponse(BaseModel):
    """Ответ на запрос инвентаря."""
    project_id: str
    node_count: int
    nodes: List[Dict[str, Any]]


class McpToolCallRequest(BaseModel):
    """Запрос на вызов MCP-инструмента."""
    tool_name: str
    arguments: Dict[str, Any]


class McpToolCallResponse(BaseModel):
    """Ответ на вызов MCP-инструмента."""
    success: bool
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class Document(BaseModel):
    """Базовый документ для RAG."""
    id: str = Field(..., description="Уникальный идентификатор")
    content: str = Field(..., description="Содержание документа")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Метаданные")
    embedding: Optional[List[float]] = Field(None, description="Векторное представление")
    created_at: datetime = Field(default_factory=datetime.now)


class RAGContext(BaseModel):
    """Контекст для LLM из RAG."""
    documents: List[Document] = Field(..., description="Релевантные документы")
    query: str = Field(..., description="Исходный запрос")
    combined_context: str = Field(..., description="Объединённый контекст для промпта")
    confidence: float = Field(..., description="Уверенность в релевантности")


class CommandTemplate(BaseModel):
    """Шаблон команды Cisco IOS."""
    command: str = Field(..., description="Команда Cisco IOS")
    description: str = Field(..., description="Описание команды")
    category: str = Field(..., description="Категория: show, configure, debug")
    device_type: str = Field(..., description="Тип устройства: router, switch")
    parameters: List[str] = Field(default_factory=list, description="Параметры команды")
    example: str = Field("", description="Пример использования")
    related_commands: List[str] = Field(default_factory=list, description="Связанные команды")

class ValidationSeverity(str, Enum):
    """Уровень серьёзности проблемы."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ValidationStatus(str, Enum):
    """Статус валидации."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"


class ValidationIssue(BaseModel):
    """Проблема, обнаруженная при валидации."""
    severity: ValidationSeverity = Field(..., description="Уровень серьёзности")
    message: str = Field(..., description="Описание проблемы")
    device: Optional[str] = Field(None, description="Устройство, к которому относится проблема")
    line: Optional[int] = Field(None, description="Номер строки в конфигурации")
    suggestion: Optional[str] = Field(None, description="Предложение по исправлению")
    rule_name: Optional[str] = Field(None, description="Имя правила, которое нарушено")


class ValidationResult(BaseModel):
    """Результат валидации."""
    status: ValidationStatus = Field(..., description="Статус валидации")
    issues: List[ValidationIssue] = Field(default_factory=list, description="Обнаруженные проблемы")
    summary: Dict[str, int] = Field(
        default_factory=lambda: {"info": 0, "warning": 0, "error": 0, "critical": 0},
        description="Сводка по типам проблем"
    )
    passed: bool = Field(..., description="Прошла ли валидация")
    timestamp: str = Field(..., description="Время проведения валидации")
    duration_ms: float = Field(..., description="Длительность валидации в мс")


class ComplianceCheck(BaseModel):
    """Проверка соответствия (compliance)."""
    name: str = Field(..., description="Имя проверки")
    description: str = Field(..., description="Описание проверки")
    passed: bool = Field(..., description="Пройдена ли проверка")
    details: Optional[str] = Field(None, description="Детали проверки")


class NetworkSnapshot(BaseModel):
    """Снимок сети для валидации."""
    project_id: str = Field(..., description="ID проекта")
    timestamp: str = Field(..., description="Время создания снимка")
    device_configs: Dict[str, str] = Field(..., description="Конфигурации устройств")
    topology: Dict[str, Any] = Field(..., description="Топология сети")


class CommandGenerationResult(BaseModel):
    commands: List[DeviceCommand] = Field(default_factory=list, description="Список сгенерированных CLI команд")

