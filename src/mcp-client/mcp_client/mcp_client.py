import json
import asyncio
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from contextlib import AsyncExitStack
from loguru import logger
from fastmcp import Client


@dataclass
class MCPTool:
    """Описание MCP-инструмента."""
    name: str
    description: str = ""
    input_schema: Dict[str, Any] = field(default_factory=dict)


class MCPClientError(Exception):
    """Ошибка MCP-клиента."""
    pass


class MCPClient:
    """
    MCP клиент на основе FastMCP.
    """
    
    def __init__(self, server_url: str, timeout: int = 60):
        self.server_url = server_url
        self.timeout = timeout
        self._client: Optional[Client] = None
        self._exit_stack: Optional[AsyncExitStack] = None
        self.tools: Dict[str, MCPTool] = {}
        self._initialized = False
    
    async def connect(self):
        """Устанавливает соединение с MCP-сервером."""
        if self._initialized:
            return self
            
        logger.info(f"Connecting to the MCP server: {self.server_url}")
        
        self._exit_stack = AsyncExitStack()
        try:
            self._client = Client(self.server_url)
            
            await self._exit_stack.enter_async_context(self._client)
            logger.info("FastMCP transport layer successfully launched.")
            
            await self._fetch_tools()
            self._initialized = True
            return self
            
        except Exception as e:
            logger.error(f"Error connecting to the server: {e}")
            await self.close()
            raise MCPClientError(f"Connection error: {e}")
            
    async def _fetch_tools(self):
        """Получает список инструментов с MCP сервера"""
        try:
            tools_response = await self._client.list_tools()
            tools_list = tools_response if isinstance(tools_response, list) else getattr(tools_response, 'tools', [])
            
            self.tools.clear()
            for tool in tools_list:
                input_schema = getattr(tool, 'inputSchema', getattr(tool, 'input_schema', {}))
                self.tools[tool.name] = MCPTool(
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=input_schema
                )
            
            logger.info(f"{len(self.tools)} tools available: {list(self.tools.keys())}")
        except Exception as e:
            logger.error(f"Error retrieving tool JSON schema: {e}")
            raise
            
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Вызывает MCP-инструмент."""
        if not self._initialized or not self._client:
            raise MCPClientError("The client is not connected to the network.")
            
        if tool_name not in self.tools:
            raise MCPClientError(f"The tool '{tool_name}' is missing on the server.")
            
        logger.info(f"Remote function call: {tool_name} with parameters {arguments}")
        
        try:
            result = await self._client.call_tool(tool_name, arguments=arguments)
            return self._parse_result(result)
        except Exception as e:
            logger.error(f"Server-side runtime error ({tool_name}): {e}")
            raise MCPClientError(f"Tool execution error: {e}")
            
    def _parse_result(self, result) -> Dict[str, Any]:
        """Парсит текстовые блоки контента и конвертирует JSON строки."""
        result_text = ""
        
        if hasattr(result, "content") and isinstance(result.content, list):
            for block in result.content:
                if hasattr(block, "text"):
                    result_text += block.text
        elif hasattr(result, "text"):
            result_text = result.text
        else:
            result_text = str(result)
            
        try:
            if result_text.strip():
                return json.loads(result_text)
        except json.JSONDecodeError:
            pass
            
        return {"text": result_text}
        
    async def close(self):
        """Освобождает порты и закрывает сетевые сессии."""
        if self._exit_stack:
            try:
                await self._exit_stack.aclose()
                logger.info("MCP sockets successfully closed and cleaned.")
            except Exception as e:
                logger.warning(f"Error during closing: {e}")
            finally:
                self._exit_stack = None
                
        self._client = None
        self._initialized = False
        self.tools.clear()

    @property
    def is_connected(self) -> bool:
        return self._initialized and self._client is not None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


def create_mcp_client(config: Dict[str, Any]) -> MCPClient:
    """Фабрика для создания клиента из файлов конфигурации."""
    server_url = config.get("server_url", "http://mcp-server:5000/mcp")
    timeout = config.get("timeout", 60)
    return MCPClient(server_url, timeout)
