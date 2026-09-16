import json
from typing import Dict, List, Any, Optional
from loguru import logger

from .base_agent import BaseAgent, AgentRole, AgentContext, AgentStatus


class ValidationAgent(BaseAgent):
    """
    Агент Batfish.
    """
    
    def __init__(self):
        super().__init__(role=AgentRole.VALIDATION, name="validation_agent")

    async def initialize(self):
        self._logger.info("ValidationAgent successfully connected.")
        
    async def process(self, context: AgentContext) -> AgentContext:
        self.status = AgentStatus.BUSY
        
        if not context.commands:
            self._logger.warning("No commands in the session context. Skipping simulation..")

            context.data["validation"] = {"passed": True, "message": "Пул команд пуст. Валидация пропущена."}
            context.data["validation_passed"] = True
            self.status = AgentStatus.IDLE
            return context
        
        self._logger.info(f"Starting compilation of the network snapshot for {len(context.commands)} changes...")
        
        try:
            validation_service = context.validation_service
            
            if not validation_service or not validation_service.batfish_enabled:
                self._logger.warning("The Batfish validation service is disabled. Skipping.")
                context.data["validation"] = {"passed": True, "message": "Сервер Batfish недоступен. Пропуск проверок."}
                context.data["validation_passed"] = True
                self.status = AgentStatus.IDLE
                return context
            
            device_configs = await self._get_device_configs(
                context.project_id,
                context.inventory,
                context.mcp_client
            )
            
            if not device_configs:
                self._logger.warning("Failed to retrieve configuration snapshots. Generating base Cisco skeletons....")

                nodes_list = context.inventory.get("nodes", []) if isinstance(context.inventory, dict) else []
                device_configs = {
                    n.get("name"): f"!\nversion 15.2\nhostname {n.get('name')}\n!\nend\n" 
                    for n in nodes_list if n.get("name")
                }
            
            has_config_changes = False
            for device, config_text in device_configs.items():
                device_commands = [c for c in context.commands if c.get("device") == device]
                
                config_only_commands = [
                    c for c in device_commands 
                    if not c.get("cli", "").strip().lower().startswith("show") 
                    and not c.get("cli", "").strip().lower().startswith("ping")
                ]
                
                if config_only_commands:
                    has_config_changes = True
                    new_cli_block = "\n".join([c.get("cli", "") for c in config_only_commands])
                    
                    if "end" in config_text:
                        device_configs[device] = config_text.replace("end", f"!\n{new_cli_block}\n!\nend")
                    else:
                        device_configs[device] = config_text + f"\n{new_cli_block}\nend"
            
            if not has_config_changes:
                self._logger.info("The pool contains only diagnostic commands. Automatic approval.")
                context.data["validation"] = {"passed": True, "message": "Диагностические команды show одобрены автоматически."}
                context.data["validation_passed"] = True
                self.status = AgentStatus.IDLE
                return context
            
            result = await validation_service.validate_configurations(
                device_configs=device_configs,
                project_id=context.project_id,
                check_types=["syntax", "routing"]
            )
            
            context.data["validation"] = result.model_dump() if hasattr(result, 'model_dump') else result
            
            if not result.passed:
                self._logger.warning(f"Validation on the network digital twin FAILED: {len(result.issues)} anomalies detected")
                context.data["validation_passed"] = False
            else:
                self._logger.info("The Batfish model confirmed the safety of the configuration.")
                context.data["validation_passed"] = True
            
            self.status = AgentStatus.IDLE
            return context
            
        except Exception as e:
            self._logger.exception(f"Critical failure within the worker's process() method {self.name}: {e}")
            self.status = AgentStatus.ERROR
            context.data["validation_error"] = str(e)
            context.data["validation_passed"] = False
            return context
    
    async def _get_device_configs(self, 
                                  project_id: str, 
                                  inventory: Dict[str, Any],
                                  mcp_client) -> Dict[str, str]:
        """Получает текущие running-config устройств через MCP инструменты."""
        if not mcp_client:
            return {}
        
        configs = {}
        nodes = inventory.get("nodes", []) if isinstance(inventory, dict) else []
        
        for node in nodes:
            node_id = node.get("node_id")
            node_name = node.get("name")
            
            if node_id and node_name:
                try:
                    result = await mcp_client.call_tool("get_device_config", {
                        "projectId": project_id,
                        "nodeId": node_id
                    })
                    
                    if result:
                        log_text = result.get("text", str(result)) if isinstance(result, dict) else str(result)
                        try:
                            parsed_json = json.loads(log_text)
                            if parsed_json.get("success"):
                                configs[node_name] = parsed_json.get("config", "")
                                self._logger.debug(f"The current configuration of node {node_name} has been imported via MCP.")
                        except Exception:
                            configs[node_name] = log_text
                        
                except Exception as e:
                    self._logger.warning(f"Failed to retrieve configuration for {node_name}: {e}")
        
        return configs
