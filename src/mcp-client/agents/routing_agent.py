from typing import Dict, List, Any, Optional
from loguru import logger
import json
from .base_agent import BaseAgent, AgentRole, AgentContext, AgentStatus
from .execute_commands_agent import CommandGenerationResult


class RoutingAgent(BaseAgent):
    """
    Генерирует конфигурационные CLI скрипты 
    для OSPF, BGP и статических маршрутов.
    """
    
    def __init__(self):
        super().__init__(role=AgentRole.ROUTING, name="routing_agent")

    async def initialize(self):
        self._logger.info("The RoutingAgent successfully connected.")

    async def process(self, context: AgentContext) -> AgentContext:
        """генерация и обогащение контекста командами маршрутизации."""
        self.status = AgentStatus.BUSY
        
        self._logger.info(f"Analysis of network routing protocols for the task: '{context.intent[:60]}...'")
        
        try:
            nodes_list = context.inventory.get("nodes", []) if isinstance(context.inventory, dict) else []
            devices = [n.get("name") for n in nodes_list if n.get("name")]

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
                            real_topology_telemetry += f"  - Маршрутизатор {node_name} имеет следующие живые интерфейсы:\n"
                            for int_name, ip, mask in interfaces_found:
                                real_topology_telemetry += f"    * Интерфейс {int_name}: IP-адрес {ip}, маска подсети {mask}\n"
                        else:
                            real_topology_telemetry += f"  - Маршрутизатор {node_name}: интерфейсы не настроены или IP отсутствуют.\n"
                            
                    except Exception as mcp_err:
                        self._logger.warning(f"Failed to read the node configuration {node_name}: {mcp_err}")

            context.data["real_topology_telemetry"] = real_topology_telemetry

            if not devices:
                context.data["error"] = "Топология пуста. Нет доступных устройств для маршрутизации."
                self.status = AgentStatus.IDLE
                return context
            
            commands = await self._generate_routing_commands(
                context.intent, 
                devices,
                context.llm_client,
                context.rag_manager,
                real_topology_telemetry
            )
            
            if not commands:
                context.data["error"] = "Агент маршрутизации сгенерировал пустой массив CLI команд"
                self.status = AgentStatus.IDLE
                return context
            
            context.commands = commands
            context.data["routing_commands"] = commands
            context.data["processed_devices"] = devices
            context.data["generated_by"] = "RoutingAgent/Ollama"
            
            self._logger.info(f"The routing worker successfully formed a pool of {len(commands)} commands.")
            self.status = AgentStatus.IDLE
            return context
            
        except Exception as e:
            self._logger.exception(f"Critical failure within the workers process() method {self.name}: {e}")
            self.status = AgentStatus.ERROR
            context.data["error"] = f"Internal failure in RoutingAgent: {str(e)}"
            return context
    
    async def _generate_routing_commands(self, 
                                         intent: str, 
                                         devices: List[str],
                                         llm_client,
                                         rag_manager,
                                         telemetry_context: str) -> List[Dict[str, str]]:
        """RAG поиск и генерация."""
        if not llm_client:
            return []
            
        rag_context = None
        if rag_manager:
            rag_context = rag_manager.get_context_for_command_generation(intent, devices)
        
        rag_text = ""
        if rag_context and rag_context.documents:
            rag_text = f"ИСПОЛЬЗУЙ СЛЕДУЮЩИЕ ШАБЛОНЫ И СИНТАКСИС МАРШРУТИЗАЦИИ:\n" \
                       f"{rag_context.combined_context}\n"
        
        prompt = f"""
{rag_text}
Высокоуровневая задача оператора: "{intent}"
Целевые узлы в топологии: [{", ".join(devices)}]
ФАКТИЧЕСКАЯ КАРТА ЖИВЫХ IP-АДРЕСОВ В СЕТИ (ДАННЫЕ ИЗ RUNNING-CONFIG):
{telemetry_context}
Сгенерируй последовательный пошаговый пул CLI команд для выполнения намерения пользователя.

СИСТЕМНЫЕ ПРАВИЛА:
1. Используй в генерируемых командах СТРОГО те имена интерфейсов, которые физически существуют на устройствах
2. Если у устройства в списке указаны интерфейсы 'FastEthernet', то используй их, а не 'GigabitEthernet'
"""
        
        try:
            result: CommandGenerationResult = await llm_client.generate_structured(
                prompt=prompt,
                response_model=CommandGenerationResult,
                system_prompt="Ты — сетевой инженер и архитектор сети. Генерируй только точный синтаксис команд."
            )
            
            if result.commands:
                return [{"device": cmd.device, "cli": cmd.cli} for cmd in result.commands]
            return []
                
        except Exception as e:
            self._logger.exception(f"Ollama API failure during routing structure generation: {e}")
            return []
