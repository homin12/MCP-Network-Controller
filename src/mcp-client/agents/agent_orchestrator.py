from typing import Dict, Any, Optional
from loguru import logger

from .base_agent import AgentContext
from .supervisor_agent import SupervisorAgent
from .routing_agent import RoutingAgent
from .config_generator_agent import ConfigAgent
from .validation_agent import ValidationAgent
from .execute_commands_agent import ExecuteCommandsAgent


class AgentOrchestrator:
    """
    Инициализирует конвейер состояний и инжектирует инфраструктурные сервисы.
    """
    
    def __init__(self,
                 mcp_client=None,
                 llm_client=None,
                 rag_manager=None,
                 validation_service=None,
                 hitl_manager=None):
        
        self.mcp_client = mcp_client
        self.llm_client = llm_client
        self.rag_manager = rag_manager
        self.validation_service = validation_service
        self.hitl_manager = hitl_manager
        
        self.supervisor = SupervisorAgent(llm_client=llm_client)
        
        self.agents = {
            "routing": RoutingAgent(),
            "config": ConfigAgent(),
            "validation": ValidationAgent(),
            "execute_commands": ExecuteCommandsAgent(),
        }
        
        for role_name, agent_instance in self.agents.items():
            self.supervisor.register_agent(role_name, agent_instance)
        
        self._initialized = False
        logger.info(f"The AgentOrchestrator complex successfully assembled. The pipeline of {len(self.agents)} workers is ready.")
    
    async def initialize(self):
        logger.info("Starting initialization of Agent Orchestrator...")
        
        try:
            if hasattr(self.supervisor, 'initialize'):
                await self.supervisor.initialize()
            
            for name, agent in self.agents.items():
                if hasattr(agent, 'initialize'):
                    await agent.initialize()
                logger.info(f"Worker agent '{name}' ready.")
            
            self._initialized = True
            logger.info("All components of the pipeline successfully launched.")
            
        except Exception as e:
            logger.error(f"Critical error during Agent Orchestrator initialization: {e}")
            self._initialized = False
            raise
    
    async def process_intent(self, 
                             intent: str, 
                             project_id: str, 
                             inventory: Dict[str, Any]) -> Dict[str, Any]:

        if not self._initialized:
            logger.warning("The orchestrator was not pre-initialized. Emergency startup...")
            await self.initialize()
        
        logger.info(f"Inbound Intent Orchestration: '{intent[:70]}...'")
        
        context = AgentContext(
            session_id=project_id,
            project_id=project_id,
            intent=intent,
            inventory=inventory,
            mcp_client=self.mcp_client,
            llm_client=self.llm_client,
            rag_manager=self.rag_manager,
            validation_service=self.validation_service,
            hitl_manager=self.hitl_manager
        )
        
        try:
            context = await self.supervisor.process(context)
            
            is_success = "error" not in context.data and "validation_error" not in context.data
            
            raw_devices = context.data.get("processed_devices", [])
            
            formatted_devices = []
            for d_name in raw_devices:
                formatted_devices.append({
                    "name": d_name,
                    "status": "started",
                    "type": "router"
                })

            result = {
                "status": "success" if is_success else "error",
                "intent": intent,
                "project_id": project_id,
                "action": context.data.get("task_type", "mixed"),
                "commands": context.commands,
                "devices": formatted_devices,
                "apply_result": context.data.get("result"),
                "validation": context.data.get("validation"),
                "validation_passed": context.data.get("validation_passed", True),
                "data": context.data
            }

            
            return result
            
        except Exception as e:
            logger.error(f"System failure within the kernel: {e}")
            import traceback
            traceback.print_exc()
            
            return {
                "status": "error",
                "intent": intent,
                "project_id": project_id,
                "error": f"Ошибка оркестратора: {str(e)}"
            }
    
    async def get_status(self) -> Dict[str, Any]:
        return {
            "initialized": self._initialized,
            "supervisor": self.supervisor.get_status(),
            "agents": {
                name: agent.get_status()
                for name, agent in self.agents.items()
            }
        }
    
    async def close(self):
        logger.info("Closing Agent Orchestrator...")
        
        if hasattr(self.supervisor, 'close'):
            await self.supervisor.close()
        
        for name, agent in self.agents.items():
            if hasattr(agent, 'close'):
                await agent.close()
            logger.info(f"Agent '{name}' closed")
        
        self._initialized = False
        logger.info("All components closed.")
