from typing import Dict, List, Any, Optional
from loguru import logger
from pydantic import BaseModel, Field

from .base_agent import BaseAgent, AgentRole, AgentContext, AgentStatus
from .execute_commands_agent import DeviceCommand


class ConfigGenerationResponse(BaseModel):
    commands: List[DeviceCommand] = Field(description="Список сгенерированных конфигурационных команд")


class ConfigAgent(BaseAgent):
    """
    Синтезирует CLI-скрипты настройки интерфейсов, VLAN и системных параметров.
    """
    
    def __init__(self):
        super().__init__(role=AgentRole.CONFIG, name="config_agent")

    async def initialize(self):
        self._logger.info("The ConfigAgent successfully connected.")
        
    async def process(self, context: AgentContext) -> AgentContext:
        self.status = AgentStatus.BUSY
        
        try:
            nodes_list = context.inventory.get("nodes", []) if isinstance(context.inventory, dict) else []
            devices = [n.get("name") for n in nodes_list if n.get("name")]
            
            if not devices:
                context.data["error"] = "Топология пуста. Нет устройств для сбора конфигураций."
                self.status = AgentStatus.IDLE
                return context
            
            self._logger.info(f"The agent requests the running-config for {len(devices)} devices via MCP....")
            real_topology_telemetry = ""
            
            for node in nodes_list:
                node_name = node.get("name")
                node_id = node.get("node_id")
                
                if node_name and node_id and context.mcp_client:
                    try:
                        mcp_res = await context.mcp_client.call_tool(
                            "get_device_config", 
                            {"projectId": context.project_id, "nodeId": node_id}
                        )
                        log_text = mcp_res.get("text", str(mcp_res)) if isinstance(mcp_res, dict) else str(mcp_res)
                        
                        import json
                        config_content = ""
                        try:
                            config_content = json.loads(log_text).get("config", "")
                        except json.JSONDecodeError:
                            try:
                                normalized_text = log_text.replace("'", '"').replace("True", "true").replace("False", "false")
                                config_content = json.loads(normalized_text).get("config", "")
                            except Exception:
                                config_content = log_text

                        import re
                        interfaces_found = re.findall(
                            r"interface\s+([\w\d/]+)\n\s+ip\s+address\s+([\d\.]+)\s+([\d\.]+)", 
                            config_content, 
                            re.IGNORECASE
                        )
                        
                        if interfaces_found:
                            real_topology_telemetry += f"  - Маршрутизатор {node_name} имеет следующие интерфейсы:\n"
                            for int_name, ip, mask in interfaces_found:
                                real_topology_telemetry += f"    * Интерфейс {int_name}: IP-адрес {ip}, маска подсети {mask}\n"
                        else:
                            real_topology_telemetry += f"  - Маршрутизатор {node_name}: интерфейсы не настроены или IP отсутствуют.\n"
                            
                    except Exception as mcp_err:
                        self._logger.warning(f"Failed to read the node configuration. {node_name}: {mcp_err}")

            context.data["real_topology_telemetry"] = real_topology_telemetry

            commands = await self._generate_config(
                context.intent,
                devices,
                context.llm_client,
                context.rag_manager,
                real_topology_telemetry
            )
            
            if not commands:
                context.data["error"] = "Агент сгенерировал пустой массив CLI команд"
                self.status = AgentStatus.IDLE
                return context
            
            context.commands = commands
            context.data["config_commands"] = commands
            context.data["processed_devices"] = devices
            context.data["generated_by"] = "ConfigAgent/Ollama"
            
            self.status = AgentStatus.IDLE
            return context
            
        except Exception as e:
            self._logger.exception(f"Critical failure within the workers process() method {self.name}: {e}")
            self.status = AgentStatus.ERROR
            context.data["error"] = str(e)
            return context
    
    async def _generate_config(self, 
                               intent: str, 
                               devices: List[str],
                               llm_client,
                               rag_manager,
                               telemetry_context: str) -> List[Dict[str, str]]:

        if not llm_client:
            return []
            
        rag_context = None
        if rag_manager:
            rag_context = rag_manager.get_context_for_command_generation(intent, devices)
        
        rag_text = ""
        if rag_context and rag_context.documents:
            rag_text = f"ОБЯЗАТЕЛЬНО ИСПОЛЬЗУЙ СЛЕДУЮЩИЕ ПРАВИЛА И СИНТАКСИС КОМАНД:\n" \
                       f"{rag_context.combined_context}\n\n"
        
        prompt = f"""
{rag_text}
Высокоуровневое намерение оператора: "{intent}"
Целевые узлы в топологии: [{", ".join(devices)}]
ФАКТИЧЕСКАЯ КАРТА IP-АДРЕСОВ В СЕТИ (ДАННЫЕ ИЗ RUNNING-CONFIG):
{telemetry_context}

Сгенерируй точные, накладываемые пошаговые CLI команды для реализации намерения.
"""
        
        try:
            response: ConfigGenerationResponse = await llm_client.generate_structured(
                prompt=prompt,
                response_model=ConfigGenerationResponse,
                system_prompt="Ты — экспертный сетевой инженер и архитектор сети. Генерируй только точный синтаксис команд."
            )
            
            return [{"device": cmd.device, "cli": cmd.cli} for cmd in response.commands]
                
        except Exception as e:
            self._logger.exception(f"Ollama API error during the generation of the configuration structure: {e}")
            return []
