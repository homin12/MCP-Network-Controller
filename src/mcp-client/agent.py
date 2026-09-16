import json
from typing import Dict, List, Any, Optional, Literal
from loguru import logger
from pydantic import BaseModel, Field

from mcp_client import MCPClient, MCPClientError, create_mcp_client
from llm.llm_factory import LLMClient, create_llm_client
from rag import RAGManager, RAGContext
from validator.validator_service import ValidationService
from hitl.manager import HITLManager
from hitl.models import ApprovalStatus, ApprovalPriority
from agents import AgentOrchestrator
from models import (
    ValidationResult, CommandGenerationResult
)


class NetworkAgent: 
        
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.mcp_client: Optional[Any] = None
        self.project_id = config.get("project_id", "")
        self._initialized = False
        
        # Конфигурация RAG.
        rag_config = config.get("rag", {})
        self.rag_enabled = rag_config.get("enabled", True)
        self.rag_manager: Optional[RAGManager] = None
        self.rag_config_cached = rag_config  

        self.llm_client: LLMClient = create_llm_client(config.get("llm", {}))

        # Конфигурация Human-in-the-Loop.
        hitl_config = config.get("hitl", {})
        self.hitl_enabled = hitl_config.get("enabled", True)
        self.hitl_manager = HITLManager(
            approval_timeout=hitl_config.get("timeout", 300),
            auto_approve_if_validated=hitl_config.get("auto_approve", False)
        )

        # Конфигурация Batfish.
        val_config = config.get("validation", {})
        self.validation_enabled = val_config.get("enabled", True)
        
        self.validation_service = ValidationService(
            batfish_host=val_config.get("batfish_host", "http://batfish:9996/v2"),
            network_name=val_config.get("network_name", "gns3_telecom_network"),
            batfish_enabled=self.validation_enabled
        )
        self._validation_initialized = False
        self.orchestrator: Optional[AgentOrchestrator] = None

        logger.info("NetworkAgent has been successfully created.")


    async def initialize(self):
        logger.info("Initializing Batfish...")
        
        if self.validation_enabled and hasattr(self, "validation_service"):
            try:
                await self.validation_service.initialize()
                self._validation_initialized = True
                logger.info("Batfish has been successfully initialized.")
            except Exception as e:
                logger.error(f"Batfish validator startup error: {e}")
                self.validation_enabled = False
                self._validation_initialized = False
        else:
            logger.info("Validation disabled, skipping")

        logger.info("RAG Initialization...")
        
        if self.rag_enabled and not self.rag_manager:
            try:
                force_rebuild = self.rag_config_cached.get("force_rebuild", False)
                self.rag_manager = RAGManager(
                    persist_directory=self.rag_config_cached.get("persist_directory", "./rag_data"),
                    collection_name=self.rag_config_cached.get("collection_name", "network_commands"),
                    project_id=self.project_id,
                    auto_load=True,
                    force_rebuild=force_rebuild
                )
                info = self.rag_manager.get_collection_info()
                logger.info(f"RAG base connected. Records in the index: {info.get('count', 0)}")
            except Exception as e:
                logger.error(f"RAG init error: {e}")
                self.rag_manager = None
                self.rag_enabled = False
        else:
            logger.info("RAG is disabled")

        logger.info("Connecting to MCP server...")
        
        mcp_config = self.config.get("mcp", {})
        self.mcp_client = create_mcp_client(mcp_config)
        await self.mcp_client.connect()
        
        logger.info(f"MCP client connected to {mcp_config.get('server_url')}")
        logger.info("MCP Tool Manifest:")
        for name, tool in self.mcp_client.tools.items():
            logger.info(f"  - {name}: {tool.description}")

        logger.info("Initializing the multi-agent core...")
        
        self.orchestrator = AgentOrchestrator(
            mcp_client=self.mcp_client,
            llm_client=self.llm_client,
            rag_manager=self.rag_manager,
            hitl_manager=self.hitl_manager,
            validation_service=self.validation_service if self.validation_enabled else None
        )
        
        await self.orchestrator.initialize()
        
        status = await self.orchestrator.get_status()
        logger.info("Agent status in the system:")
        logger.info(f"   Supervisor: {status['supervisor']['status']}")
        for name, agent_status in status['agents'].items():
            logger.info(f"   - {name}: {agent_status['status']}")

        try:
            from observability.metrics import metrics
            if self.rag_manager:
                info = self.rag_manager.get_collection_info()
                metrics.update_rag_collection_size(info.get('count', 0))
            metrics.update_mcp_servers(1)
        except ImportError:
            pass

        self._initialized = True
        
        return self

    
    async def process_intent(self, intent_text: str, project_id: Optional[str] = None) -> Dict[str, Any]:
        if not self._initialized:
            await self.initialize()
        
        pid = project_id or self.project_id
        if not pid:
            raise ValueError("Project ID не указан")
        
        try:
            # Сбор контекста сети через MCP.
            inventory = await self._get_inventory(pid)
            nodes = inventory.get("nodes", []) if isinstance(inventory, dict) else []
            
            logger.info(f"Inventory retrieved: {len(nodes)} devices detected")
            for node in nodes[:5]:
                logger.info(f"   - Node: {node.get('name')} | Status: {node.get('status')}")
            if len(nodes) > 5:
                logger.info(f"   ... and more {len(nodes) - 5} devices in topology")
                
        except MCPClientError as e:
            logger.error(f"MCP failure during the inventory collection phase: {e}")
            return {
                "status": "error",
                "intent": intent_text,
                "project_id": pid,
                "error": f"Ошибка MCP: {str(e)}"
            }

        logger.info("Delegating the task to the multi-agent core...")
        
        try:
            result = await self.orchestrator.process_intent(
                intent=intent_text,
                project_id=pid,
                inventory=inventory
            )
            
            # Извлекаем финальный статус.
            mas_status = result.get('status', 'unknown')
            generated_cmds = result.get('commands', [])
            cmds_count = len(generated_cmds) if isinstance(generated_cmds, list) else 0
            
            logger.info(f"   The system completed processing the task with the status: [{mas_status.upper()}]")
            logger.info(f"   Classified task type: {result.get('action', 'unknown')}")
            logger.info(f"   Number of AI commands: {cmds_count}")
            
            return result
            
        except Exception as e:
            logger.error(f"Unexpected exception in the pipeline: {e}")
            import traceback
            traceback.print_exc()
            return {
                "status": "error",
                "intent": intent_text,
                "project_id": pid,
                "error": f"Внутренняя ошибка в агенте: {str(e)}"
            }
    
    
    async def _get_inventory(self, project_id: str) -> Dict[str, Any]:
        """
        Получение инвентаря через MCP инструмент get_inventory.
        """
        logger.info("Inventory request via MCP...")
        
        try:
            result = await self.mcp_client.call_tool("get_inventory", {
                "projectId": project_id
            })
            
            if "content" in result and isinstance(result["content"], list):
                for item in result["content"]:
                    if item.get("type") == "text":
                        text = item.get("text", "")
                        try:
                            parsed = json.loads(text)
                            logger.info(f"Inventory received: {parsed.get('node_count', 0)} devices")
                            return parsed
                        except json.JSONDecodeError:
                            pass
            
            return result
            
        except MCPClientError as e:
            logger.error(f"MCP error retrieving inventory: {e}")
            return {"nodes": []}
        except Exception as e:
            logger.error(f"Error retrieving inventory: {e}")
            return {"nodes": []}

    
    async def close(self):
        logger.info("Closing Network Agent...")
        
        if self.orchestrator:
            await self.orchestrator.close()
        
        if self.mcp_client:
            await self.mcp_client.close()
        
        if self.validation_enabled and self.validation_service:
            await self.validation_service.close()
                
        self._initialized = False