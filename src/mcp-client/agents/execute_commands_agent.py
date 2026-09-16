import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional, Set
from loguru import logger
from pydantic import BaseModel, Field

from .base_agent import BaseAgent, AgentRole, AgentStatus, AgentMessage, AgentContext


class DeviceCommand(BaseModel):
    device: str = Field(description="Имя или IP-адрес сетевого устройства (например, R1)")
    cli: str = Field(description="Атомарная конфигурационная или show команда")

class CommandGenerationResult(BaseModel):
    commands: List[DeviceCommand] = Field(description="Последовательный список команд для выполнения")
    reasoning: str = Field(description="Логическое обоснование генерации этого набора команд")
    devices_processed: List[str] = Field(description="Список задействованных имен устройств")


class ExecuteCommandsAgent(BaseAgent):  
    def __init__(self):
        super().__init__(
            role=AgentRole.EXECUTE_COMMANDS,
            name="execute_commands_agent"
        )
        self._llm_client = None
    
    async def initialize(self):
        self._logger.info("The ExecuteCommandsAgent successfully initialized.")
    
    async def process(self, context: AgentContext) -> AgentContext:
        self.status = AgentStatus.BUSY
                
        try:
            self._llm_client = getattr(context, "llm_client", None)
            if not self._llm_client:
                context.data["error"] = "LLM клиент недоступен в контексте сессии"
                self.status = AgentStatus.IDLE
                return context
            
            target_devices = context.data.get("target_devices", [])
            nodes = context.inventory.get("nodes", []) if isinstance(context.inventory, dict) else []
            device_names = [n.get("name") for n in nodes if n.get("name")]
            
            if not target_devices:
                target_devices = device_names
                context.data["target_devices"] = target_devices
            
            if not target_devices:
                context.data["error"] = "Топология пуста. Нет доступных устройств для автоматизации."
                self.status = AgentStatus.IDLE
                return context
            
            self._logger.info(f"The agent requests the running-config for {len(target_devices)} devices via MCP....")
            telemetry_context = ""
            
            for node in nodes:
                node_name = node.get("name")
                node_id = node.get("node_id")
                
                if node_name in target_devices and node_id and context.mcp_client:
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
                        
                        interface_blocks = re.findall(r"(interface\s+[\w\d/\.]+.*?)(?=\n!)", config_content, re.DOTALL | re.IGNORECASE)
                        
                        interfaces_found = []
                        for block in interface_blocks:
                            name_match = re.match(r"interface\s+([\w\d/\.]+)", block, re.IGNORECASE)
                            ip_match = re.search(r"ip\s+address\s+([\d\.]+)\s+([\d\.]+)", block, re.IGNORECASE)
                            
                            if name_match and ip_match:
                                int_name = name_match.group(1)
                                ip_addr = ip_match.group(1)
                                mask_addr = ip_match.group(2)
                                interfaces_found.append((int_name, ip_addr, mask_addr))

                        if interfaces_found:
                            telemetry_context += f"  - Устройство {node_name} имеет следующие IP:\n"
                            for int_name, ip, mask in interfaces_found:
                                telemetry_context += f"    * {int_name}: IP {ip} (Mask: {mask})\n"
                        else:
                            telemetry_context += f"  - Устройство {node_name}: нет настроенных IP.\n"
                            
                    except Exception as mcp_err:
                        self._logger.warning(f"Failed to read the node configuration. {node_name}: {mcp_err}")

            context.data["real_topology_telemetry"] = telemetry_context
            
            intent_text = getattr(context, "intent", "show running-config")
            rag_manager = getattr(context, "rag_manager", None)

            commands = await self._generate_commands(
                intent=intent_text,
                devices=target_devices,
                inventory=context.inventory,
                rag_manager=rag_manager,
                telemetry_context=telemetry_context
            )
            
            if not commands:
                context.data["error"] = "ИИ не смог декомпозировать намерение в пулы CLI команд"
                self.status = AgentStatus.IDLE
                return context
            
            context.commands = commands
            context.data["generated_commands"] = commands
            context.data["processed_devices"] = target_devices
            
            self.status = AgentStatus.IDLE
            return context
            
        except Exception as e:
            self._logger.error(f"Critical failure within the agents process() method {self.name}: {e}")
            self.status = AgentStatus.ERROR
            context.data["error"] = f"Internal crash in {self.name}: {str(e)}"
            return context

    
    async def _generate_commands(self, intent: str, devices: List[str], inventory: Dict[str, Any], rag_manager, telemetry_context: str) -> List[Dict[str, str]]:
        rag_context = None
        if rag_manager:
            rag_context = rag_manager.get_context_for_command_generation(intent, devices)
        
        rag_text = ""
        if rag_context and rag_context.documents:
            rag_text = f"СПРАВОЧНЫЕ ШАБЛОНЫ КОМАНД ИЗ БАЗЫ ЗНАНИЙ:\n{rag_context.combined_context}\n"
            
        device_info = self._get_device_info(inventory, devices)

        prompt = f"""
{rag_text}
ВЫСОКОУРОВНЕВОЕ НАМЕРЕНИЕ ОПЕРАТОРА: "{intent}"
СПИСОК ДОСТУПНЫХ УСТРОЙСТВ: [{", ".join(device_info)}]

АКТУАЛЬНАЯ КАРТА IP-АДРЕСОВ ИНТЕРФЕЙСОВ В СЕТИ:
{telemetry_context}

ЗАДАНИЕ ДЛЯ LLM:
Сгенерируй точные команды для выполнения намерения пользователя.
"""
        try:
            result = await self._llm_client.generate_structured(
                prompt=prompt,
                response_model=CommandGenerationResult,
                system_prompt="Ты — экспертный сетевой инженер. Твоя задача — подставлять реальные IP вместо имен в команды."
            )
            if result.commands:
                return [{"device": cmd.device, "cli": cmd.cli} for cmd in result.commands]
            return []
        except Exception as e:
            self._logger.exception(f"LLM error: {e}")
            return []
    
    def _get_device_info(self, inventory: Dict[str, Any], devices: List[str]) -> Dict[str, Any]:
        device_info = {}
        nodes = inventory.get("nodes", []) if isinstance(inventory, dict) else []
        
        for node in nodes:
            name = node.get("name")
            if name in devices:
                device_info[name] = {
                    "type": node.get("type", "router"),
                    "status": node.get("status", "unknown"),
                    "console": node.get("console"),
                    "node_id": node.get("node_id")
                }
        return device_info


    def _get_device_info(self, inventory: Dict[str, Any], devices: List[str]) -> Dict[str, Any]:
        device_info = {}
        nodes = inventory.get("nodes", []) if isinstance(inventory, dict) else []
        
        for node in nodes:
            name = node.get("name")
            if name in devices:
                properties = node.get("properties", {})
                
                real_ip = (
                    node.get("management_ip") or 
                    node.get("host") or 
                    properties.get("ip") or 
                    "unknown"
                )
                
                device_info[name] = {
                    "type": node.get("type", "router"),
                    "status": node.get("status", "unknown"),
                    "console": node.get("console"),
                    "node_id": node.get("node_id"),
                    "ip": real_ip
                }
        
        return device_info


    async def handle_message(self, message: AgentMessage) -> Dict[str, Any]:
        content = message.content
        if content.get("type") == "run_pipeline_step":
            context_obj = content.get("context")
            if context_obj and isinstance(context_obj, AgentContext):
                updated_context = await self.process(context_obj)
                return {"status": "success", "context": updated_context}
            return {"status": "error", "error": "В транзакции отсутствует объект AgentContext"}
            
        return {"status": "success", "message": f"Агент {self.name} успешно прочитал фрейм."}
