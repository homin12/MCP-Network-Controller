import asyncio
from enum import Enum
from typing import Dict, List, Any, Optional
from loguru import logger
from pydantic import BaseModel, Field

from .base_agent import BaseAgent, AgentRole, AgentContext, AgentStatus


class TaskType(str, Enum):
    """Типы сетевых подзадач."""
    INFORMATIONAL = "informational"
    ROUTING = "routing"
    CONFIG = "config"
    VALIDATION = "validation"
    EXECUTE_COMMANDS = "execute_commands"
    MIXED = "mixed"


class IntentAnalysis(BaseModel):
    """Схема для валидации классификации намерений."""
    task_type: TaskType = Field(description="Тип сетевой задачи")
    target_devices: List[str] = Field(default_factory=list, description="Целевые узлы в топологии (если указаны)")
    requires_config: bool = Field(default=False, description="Флаг необходимости изменения конфигурации (True/False)")
    requires_validation: bool = Field(default=False, description="Флаг необходимости пре-валидации в Batfish (True/False)")
    reasoning: str = Field(description="Логическое обоснование классификации диспетчером")
	

class SupervisorAgent(BaseAgent): 
    """
    Осуществляет декомпозицию намерений пользователя, 
    классифицирует тип задачи с помощью LLM и последовательно пропускает 
    контекст по цепочке специализированных воркеров.
    """
    def __init__(self, llm_client=None):
        super().__init__(role=AgentRole.SUPERVISOR, name="supervisor_agent")
        self.llm_client = llm_client
        self._agents: Dict[str, BaseAgent] = {}
        self._initialized = False
        self._analysis_timeout = 360
    
    async def initialize(self):      
        for name, agent in self._agents.items():
            if hasattr(agent, 'initialize'):
                await agent.initialize()
        self._initialized = True
        self._logger.info("The pipeline is ready for operation..")
    
    def register_agent(self, role_key: str, agent: BaseAgent):
        self._agents[role_key] = agent

    async def process(self, context: AgentContext) -> AgentContext:
        self.status = AgentStatus.BUSY
                
        try:
            # Запускаем Ollama для классификации интента.
            analysis = await self._analyze_intent_with_timeout(context.intent, context.inventory)
            
            if not analysis:
                context.data["error"] = "ИИ классификации вернул пустой результат."
                self.status = AgentStatus.IDLE
                return context
                
            # Обогащаем контекст сессии метаданными анализа.
            context.data["task_type"] = analysis.task_type.value
            context.data["target_devices"] = analysis.target_devices
            context.data["requires_config"] = analysis.requires_config
            context.data["requires_validation"] = analysis.requires_validation
            context.data["reasoning"] = analysis.reasoning
            
            self._logger.info(f"The intent classified as [{analysis.task_type.value}]. Rationale: {analysis.reasoning}")
            
            # Передаем контекст специализированным воркерам.
            if analysis.task_type == TaskType.INFORMATIONAL:
                context = await self._handle_informational(context)
                
            elif analysis.task_type == TaskType.EXECUTE_COMMANDS:
                context = await self._handle_execute_commands(context)
                
            elif analysis.task_type == TaskType.ROUTING:
                context = await self._delegate_to_agent("routing", context)
                
            elif analysis.task_type == TaskType.CONFIG:
                context = await self._delegate_to_agent("config", context)
                
            elif analysis.task_type == TaskType.MIXED:
                context = await self._handle_mixed(context)
            
            if context.commands and analysis.task_type != TaskType.INFORMATIONAL:
                normalized_commands = []
                for cmd in context.commands:
                    device = cmd.get("device")
                    cli_raw = cmd.get("cli", "")
                    
                    # Если LLM засунула несколько команд через перенос строки.
                    if "\n" in cli_raw:
                        # Разбиваем строку на отдельные команды и очищаем от пробелов.
                        sub_commands = [line.strip() for line in cli_raw.split("\n") if line.strip()]
                        for sub_cmd in sub_commands:
                            normalized_commands.append({
                                "device": device,
                                "cli": sub_cmd
                            })
                    else:
                        normalized_commands.append(cmd)
                
                context.commands = normalized_commands
                
                # Пре-валидация Batfish.
                if analysis.requires_validation and "validation" in self._agents:
                    self._logger.info("Simulation required. Redirecting to ValidationAgent....")
                    context = await self._delegate_to_agent("validation", context)
                    
                    if not context.data.get("validation_passed", True):
                        self._logger.warning("Deployment blocked: the Batfish detected critical anomalies")
                        self.status = AgentStatus.IDLE
                        return context

                # Деплой изменений в сеть.
                if context.mcp_client:
                    self._logger.info(f"Deployment: Supervisor sends {len(context.commands)} commands to the MCP server....")
                    
                    mcp_response = await context.mcp_client.call_tool(
                        "apply_config",
                        {
                            "projectId": context.project_id,
                            "commands": context.commands
                        }
                    )
                    
                    # Разбираем текстовый аутпут терминала роутеров.
                    log_text = mcp_response.get("text", str(mcp_response)) if isinstance(mcp_response, dict) else str(mcp_response)
                    try:
                        import json
                        apply_result = json.loads(log_text)
                    except Exception:
                        apply_result = {"output": log_text}
                    
                    context.data["result"] = apply_result
                    self._logger.info("The deployment transaction has been successfully completed and recorded in the context.")

            self.status = AgentStatus.IDLE
            return context
            
        except asyncio.TimeoutError:
            self._logger.error("Timeout Ollama API")
            self.status = AgentStatus.ERROR
            context.data["error"] = f"Превышен таймаут инференса ИИ модели ({self._analysis_timeout}с)"
            return context
            
        except Exception as e:
            self._logger.exception(f"Unexpected failure in the Supervisor: {e}")
            self.status = AgentStatus.ERROR
            context.data["error"] = str(e)
            return context
    
    async def _analyze_intent_with_timeout(self, intent: str, inventory: Dict[str, Any]) -> Optional[IntentAnalysis]:
        try:
            return await asyncio.wait_for(
                self._analyze_intent(intent, inventory),
                timeout=self._analysis_timeout
            )
        except asyncio.TimeoutError:
            raise
    
    async def _analyze_intent(self, intent: str, inventory: Dict[str, Any]) -> Optional[IntentAnalysis]:
        nodes_list = inventory.get("nodes", []) if isinstance(inventory, dict) else []
        devices = [n.get("name") for n in nodes_list if n.get("name")]
        devices_str = ", ".join(devices) if devices else "нет доступных устройств"
        
        prompt = f"""
Проанализируй высокоуровневый запрос сетевого оператора и определи ТИП ЗАДАЧИ.

ЗАПРОС ОПЕРАТОРА: "{intent}"
ТЕКУЩИЕ АКТИВНЫЕ УЗЛЫ СЕТИ: [{devices_str}]

КАТЕГОРИИ КЛАССИФИКАЦИИ (Поле 'task_type'):
1. "informational" - запрос информации (покажи, какие роутеры есть, выведи список, статус узлов)
2. "execute_commands" - выполнение show-команд просмотра (выполни, запусти команду, show ip interface, brief)
3. "routing" - настройка или изменение протоколов маршрутизации (OSPF, BGP, статические маршруты)
4. "config" - общее изменение конфигурации сетевых интерфейсов или VLAN (настрой, измени, пропиши IP)
5. "mixed" - смешанный комплексный запрос
"""
        
        try:
            if self.llm_client:
                analysis_result: IntentAnalysis = await self.llm_client.generate_structured(
                    prompt=prompt,
                    response_model=IntentAnalysis,
                    system_prompt="Ты — главный диспетчер и классификатор сетевых задач. Отвечай кратко и строго в формате JSON."
                )
                return self._validate_analysis(analysis_result, intent)
            return None
                
        except Exception as e:
            self._logger.error(f"Ollama API error during the classification stage: {e}")
            return None

    def _validate_analysis(self, analysis: IntentAnalysis, intent: str) -> IntentAnalysis:
        intent_lower = intent.lower()
        if "выполни" in intent_lower or "команду" in intent_lower or "запусти" in intent_lower:
            if analysis.task_type != TaskType.EXECUTE_COMMANDS and "show" in intent_lower:
                analysis.task_type = TaskType.EXECUTE_COMMANDS
                analysis.reasoning = "Исправлено защитной эвристикой: намерение требует интерактивного выполнения show команд просмотра"
        return analysis
    
    async def _handle_informational(self, context: AgentContext) -> AgentContext:
        nodes = context.inventory.get("nodes", []) if isinstance(context.inventory, dict) else []
        context.data["result"] = {
            "type": "informational",
            "devices": [
                {"name": n.get("name"), "status": n.get("status"), "type": n.get("type", "router")}
                for n in nodes
            ],
            "count": len(nodes)
        }
        return context
    
    async def _handle_execute_commands(self, context: AgentContext) -> AgentContext:            
        return await self._delegate_to_agent("execute_commands", context)
    
    async def _delegate_to_agent(self, agent_name: str, context: AgentContext) -> AgentContext:
        if agent_name not in self._agents:
            self._logger.warning(f"The requested worker [{agent_name}] is missing from the Supervisor registry.")
            context.data["error"] = f"Сбой оркестрации: специализированный агент '{agent_name}' не зарегистрирован"
            return context
        
        agent = self._agents[agent_name]        
        return await agent.process(context)
    
    async def _handle_mixed(self, context: AgentContext) -> AgentContext:
        """Последовательная обработка конвейера задач."""
        context = await self._handle_informational(context)
        
        if "config" in self._agents and context.data.get("requires_config", False):
            context = await self._delegate_to_agent("config", context)
        
        if "validation" in self._agents and context.data.get("requires_validation", False):
            context = await self._delegate_to_agent("validation", context)
        
        return context
    
    async def close(self):
        self._initialized = False
        self._logger.info(f"Orchestrator {self.name} successfully unloaded.")
