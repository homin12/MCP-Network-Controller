from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum


class ApprovalStatus(str, Enum):
    """Статус запроса на утверждение."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ApprovalPriority(str, Enum):
    """Приоритет запроса."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ApprovalRequest(BaseModel):
    """Запрос на утверждение."""
    id: str = Field(..., description="Уникальный ID запроса")
    session_id: str = Field(..., description="ID сессии")
    intent: str = Field(..., description="Исходное намерение пользователя")
    project_id: str = Field(..., description="ID проекта")
    commands: List[Dict[str, str]] = Field(..., description="Команды для выполнения")
    validation_result: Optional[Dict[str, Any]] = Field(None, description="Результат валидации")
    status: ApprovalStatus = Field(default=ApprovalStatus.PENDING, description="Статус запроса")
    priority: ApprovalPriority = Field(default=ApprovalPriority.MEDIUM, description="Приоритет")
    created_at: datetime = Field(default_factory=datetime.now, description="Время создания")
    expires_at: datetime = Field(..., description="Время истечения")
    approved_at: Optional[datetime] = Field(None, description="Время утверждения")
    rejected_at: Optional[datetime] = Field(None, description="Время отклонения")
    approved_by: Optional[str] = Field(None, description="Кто утвердил")
    reason: Optional[str] = Field(None, description="Причина отклонения")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Дополнительные данные")


class ApprovalResponse(BaseModel):
    """Ответ на запрос утверждения."""
    request_id: str = Field(..., description="ID запроса")
    status: ApprovalStatus = Field(..., description="Новый статус")
    reason: Optional[str] = Field(None, description="Причина решения")
    timestamp: datetime = Field(default_factory=datetime.now, description="Время решения")


class PendingApproval(BaseModel):
    """Ожидающий утверждения запрос (для UI)."""
    id: str
    intent: str
    project_id: str
    commands_count: int
    priority: str
    created_at: str
    expires_in: str
    validation_passed: bool
    has_issues: bool