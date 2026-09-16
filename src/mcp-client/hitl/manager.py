import uuid
import json
import asyncio
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from loguru import logger
import os
from .models import (
    ApprovalRequest,
    ApprovalResponse,
    ApprovalStatus,
    ApprovalPriority,
    PendingApproval
)


class HITLManager:
    """
    Менеджер Human-in-the-Loop.
    """
    def __init__(self, approval_timeout: int = 300, 
                 auto_approve_if_validated: bool = False,
                 storage_path: str = "./hitl_data"):

        self.approval_timeout = approval_timeout
        self.auto_approve_if_validated = auto_approve_if_validated
        self.storage_path = storage_path
        
        self._pending_requests: Dict[str, ApprovalRequest] = {}
        self._history: List[ApprovalRequest] = []
        self._approval_callbacks: Dict[str, asyncio.Event] = {}
        
        os.makedirs(storage_path, exist_ok=True)
        logger.info(f"HITL ititialized. Session timeout: {approval_timeout}с")
            
    async def request_approval(self, 
                               intent: str,
                               project_id: str,
                               commands: List[Dict[str, str]],
                               validation_result: Optional[Dict[str, Any]] = None,
                               priority: ApprovalPriority = ApprovalPriority.MEDIUM,
                               metadata: Dict[str, Any] = None) -> ApprovalResponse:
        """
        Регистрирует запрос на изменение конфигурации сети и ставит выполнение на паузу.
        """
        request_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())
        
        request = ApprovalRequest(
            id=request_id,
            session_id=session_id,
            intent=intent,
            project_id=project_id,
            commands=commands,
            validation_result=validation_result,
            status=ApprovalStatus.PENDING,
            priority=priority,
            created_at=datetime.now(),
            expires_at=datetime.now() + timedelta(seconds=self.approval_timeout),
            metadata=metadata or {}
        )
        
        self._pending_requests[request_id] = request
        self._approval_callbacks[request_id] = asyncio.Event()

        if self.auto_approve_if_validated and validation_result and validation_result.get("passed", False):
            logger.info(f"HITL: Auto aprove")
            response = ApprovalResponse(
                request_id=request_id,
                status=ApprovalStatus.APPROVED,
                reason="Автоматическое утверждение (валидация пройдена)"
            )
            await self._process_response(response)
            return response
        
        logger.info(f"HITL: Scenario paused. Awaiting approval ID: {request_id}")
        
        try:
            await asyncio.wait_for(
                self._approval_callbacks[request_id].wait(),
                timeout=self.approval_timeout
            )
        except asyncio.TimeoutError:
            logger.warning(f"HITL: Waiting session {request_id} timed out. ({self.approval_timeout}с)")
            if request_id in self._pending_requests:
                req = self._pending_requests[request_id]
                req.status = ApprovalStatus.EXPIRED
                req.reason = "Автоматическое отклонение: истекло время ожидания ответа оператора"
                self._history.append(req)
                del self._pending_requests[request_id]
                self._save_to_storage()
                
            return ApprovalResponse(
                request_id=request_id,
                status=ApprovalStatus.EXPIRED,
                reason="Истекло время ожидания утверждения оператором"
            )
        
        request = self.get_request(request_id)
        if request and request.status != ApprovalStatus.PENDING:
            return ApprovalResponse(
                request_id=request_id,
                status=request.status,
                reason=request.reason
            )
        
        return ApprovalResponse(
            request_id=request_id,
            status=ApprovalStatus.EXPIRED,
            reason="Запрос аннулирован"
        )
    
    async def approve_request(self, request_id: str, approver: str = "operator") -> ApprovalResponse:
        """Внешний метод API для подтверждения заливки команд."""
        return await self._process_response(ApprovalResponse(
            request_id=request_id,
            status=ApprovalStatus.APPROVED,
            reason=f"Утверждено оператором {approver}"
        ))
    
    async def reject_request(self, request_id: str, reason: str = "Отклонено оператором") -> ApprovalResponse:
        """Внешний метод API для отмены и блокировки пула изменений."""
        return await self._process_response(ApprovalResponse(
            request_id=request_id,
            status=ApprovalStatus.REJECTED,
            reason=reason
        ))
    
    async def _process_response(self, response: ApprovalResponse) -> ApprovalResponse:
        request_id = response.request_id
        
        if request_id not in self._pending_requests:
            return response
        
        request = self._pending_requests[request_id]
        
        if request.status != ApprovalStatus.PENDING:
            logger.warning(f"Request {request_id} already processed: {request.status}")
            return response
        
        if response.status == ApprovalStatus.APPROVED:
            request.status = ApprovalStatus.APPROVED
            request.approved_at = datetime.now()
            request.reason = response.reason
        elif response.status == ApprovalStatus.REJECTED:
            request.status = ApprovalStatus.REJECTED
            request.rejected_at = datetime.now()
            request.reason = response.reason
        
        self._history.append(request)
        del self._pending_requests[request_id]
        
        if request_id in self._approval_callbacks:
            self._approval_callbacks[request_id].set()
            del self._approval_callbacks[request_id]
        
        self._save_to_storage()
        return response
    
    def get_pending_requests(self) -> List[PendingApproval]:
        """Возвращает список активных сессий ожидания."""
        result = []
        now = datetime.now()
        
        for request in self._pending_requests.values():
            expires_in = request.expires_at - now
            seconds_left = max(0, int(expires_in.total_seconds()))
            
            result.append(PendingApproval(
                id=request.id,
                intent=request.intent[:200],
                project_id=request.project_id,
                commands_count=len(request.commands),
                priority=request.priority.value if hasattr(request.priority, 'value') else str(request.priority),
                created_at=request.created_at.isoformat(),
                expires_in=f"{seconds_left}с",
                validation_passed=request.validation_result.get("passed", False) if request.validation_result else False,
                has_issues=len(request.validation_result.get("issues", [])) > 0 if request.validation_result else False
            ))
        return result
    
    def get_request(self, request_id: str) -> Optional[ApprovalRequest]:
        if request_id in self._pending_requests:
            return self._pending_requests[request_id]
        for req in self._history:
            if req.id == request_id:
                return req
        return None
    
    async def get_status(self, request_id: str) -> Optional[ApprovalStatus]:
        request = self.get_request(request_id)
        return request.status if request else None
    
    def _save_to_storage(self):
        history_file = os.path.join(self.storage_path, "history.json")
        try:
            serialized_list = [json.loads(r.model_dump_json()) for r in self._history]
            with open(history_file, 'w', encoding='utf-8') as f:
                json.dump(serialized_list, f, ensure_ascii=False, indent=2)
            logger.debug(f"HITL audit log saved to file: {history_file}")
        except Exception as e:
            logger.warning(f"Failed to write the approval history to disk: {e}")