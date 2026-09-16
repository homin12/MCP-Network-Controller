from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
import uuid
from loguru import logger
from datetime import datetime

class AgentRole(str, Enum):
    """Роли интеллектуальных агентов в пайплайне."""
    SUPERVISOR = "supervisor"
    ROUTING = "routing"
    CONFIG = "config"
    VALIDATION = "validation"
    EXECUTE_COMMANDS = "execute_commands" 
    SECURITY = "security"
    NETWORK_OPTIMIZER = "network_optimizer"


class AgentStatus(str, Enum):
    """Статусы жизненного цикла воркеров."""
    IDLE = "idle"
    BUSY = "busy"
    ERROR = "error"
    STOPPED = "stopped"


@dataclass
class AgentMessage:
    """Сообщение между агентами."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    sender: str = ""
    recipient: str = ""
    content: Dict[str, Any] = field(default_factory=dict)
    message_type: str = "request"
    timestamp: datetime = field(default_factory=datetime.now)
    correlation_id: Optional[str] = None
    requires_response: bool = True
    response: Optional[Dict[str, Any]] = None


@dataclass
class AgentContext:
    """
    Единый разделяемый контекст выполнения транзакции.
    """
    session_id: str                          # Trace ID сессии.
    project_id: str                          # ID активного проекта.
    intent: str                              # Бизнес-задача оператора.
    inventory: Dict[str, Any]                # Актуальный слепок топологии сети.
    commands: List[Dict[str, str]] = field(default_factory=list) # Сгенерированные ИИ CLI-команды.
    data: Dict[str, Any] = field(default_factory=dict)           # Метаданные (логи, алерты).
    
    mcp_client: Any = None
    llm_client: Any = None
    rag_manager: Any = None
    validation_service: Any = None
    hitl_manager: Any = None


class BaseAgent(ABC):   
    def __init__(self, role: AgentRole, name: str = None):
        self.agent_id = str(uuid.uuid4())[:8]
        self.role = role
        self.name = name or f"{role.value}_{self.agent_id}"
        self.status = AgentStatus.IDLE
        self._logger = logger.bind(agent=self.name, role=self.role.value)
    
    @abstractmethod
    async def process(self, context: AgentContext) -> AgentContext:
        """
        Принимает контекст, выполняет логику специализации, обогащает контекст и возвращает его.
        """
        pass
    
    async def initialize(self):
        """Асинхронная подготовка ресурсов воркера."""
        pass
    
    async def close(self):
        pass
    
    def get_status(self) -> Dict[str, Any]:
        """Возвращает телеметрию состояния агента для Prometheus."""
        return {
            "id": self.agent_id,
            "name": self.name,
            "role": self.role.value,
            "status": self.status.value
        }
