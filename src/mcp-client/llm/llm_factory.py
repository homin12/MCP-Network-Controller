import ollama
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Type
from loguru import logger
from pydantic import BaseModel, Field
from rag import RAGManager, RAGContext

from models import RAGContext


class LLMClient(ABC):
    def __init__(self, rag_manager: Optional[Any] = None):
        self.rag_manager = rag_manager
    
    @abstractmethod
    async def generate_response(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Генерация обычного текста (диалог, объяснения)."""
        pass
    
    @abstractmethod
    async def generate_structured(self, prompt: str, response_model: Type[BaseModel], 
                                  system_prompt: Optional[str] = None) -> BaseModel:
        """Генерация JSON по Pydantic-схеме."""
        pass

    @abstractmethod
    async def predict_tool_call(self, prompt: str, mcp_tools: List[Dict[str, Any]], 
                                system_prompt: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Принимает динамический список инструментов от MCP и заставляет LLM выбрать нужный."""
        pass


class OllamaClient(LLMClient):
    def __init__(self, model: str = "qwen2.5:14b", host: str = "http://ollama:11434",
                 rag_manager: Optional[Any] = None):
        super().__init__(rag_manager)
        self.model = model
        self.host = host
        self._client = ollama.AsyncClient(host=host)
        logger.info(f"Ollama client initialized. Model: {model}, RAG connected.")
    
    def _build_messages(self, prompt: str, system_prompt: Optional[str] = None) -> List[Dict[str, str]]:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return messages

    async def generate_response(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        messages = self._build_messages(prompt, system_prompt)
        try:
            response = await self._client.chat(
                model=self.model,
                messages=messages,
                options={"temperature": 0.1, "num_predict": 2048}
            )
            return response["message"]["content"]
        except Exception as e:
            logger.error(f"Ollama API critical error (generate_response): {e}")
            raise RuntimeError(f"Сбой локальной LLM: {e}")
            
    async def generate_structured(self, prompt: str, response_model: Type[BaseModel], 
                                  system_prompt: Optional[str] = None) -> BaseModel:
        messages = self._build_messages(prompt, system_prompt)
        try:
            response = await self._client.chat(
                model=self.model,
                messages=messages,
                format=response_model.model_json_schema(), 
                options={"temperature": 0.0} 
            )
            raw_content = response["message"]["content"]
            return response_model.model_validate_json(raw_content)
        except Exception as e:
            logger.error(f"Ollama Structured Outputs Error ({response_model.__name__}): {e}")
            raise RuntimeError(f"LLM не смогла построить валидный JSON: {e}")

    async def predict_tool_call(self, prompt: str, mcp_tools: List[Dict[str, Any]], 
                                system_prompt: Optional[str] = None) -> Optional[Dict[str, Any]]:
        messages = self._build_messages(prompt, system_prompt)
        try:
            response = await self._client.chat(
                model=self.model,
                messages=messages,
                tools=mcp_tools,
                options={"temperature": 0.0}
            )
            
            message = response.get("message", {})
            if "tool_calls" in message and message["tool_calls"]:
                tool_call = message["tool_calls"][0]
                logger.info(f"LLM choose MCP-tool: {tool_call['function']['name']}")
                return {
                    "name": tool_call["function"]["name"],
                    "arguments": tool_call["function"]["arguments"]
                }
            
            logger.warning("LLM decided not to call the tool and responded with text.")
            return None
            
        except Exception as e:
            logger.error(f"Error Ollama Tool Calling: {e}")
            raise RuntimeError(f"Failed to match prompt with MCP tools: {e}")


class StubLLMClient(LLMClient):
    def __init__(self, rag_manager: Optional[RAGManager] = None):
        super().__init__(rag_manager)
    
    async def generate_response(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        return "Тестовый ответ-заглушка."
    
    async def generate_structured(self, prompt: str, response_model: Type[BaseModel], 
                                  system_prompt: Optional[str] = None) -> BaseModel:
        return response_model()
    
    async def predict_tool_call(self, prompt: str, mcp_tools: List[Dict[str, Any]], 
                                system_prompt: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return {
            "name": "ApplyNetworkConfig",
            "arguments": {
                "deviceIp": "192.168.1.1",
                "username": "admin",
                "password": "cisco",
                "commands": ["interface Gi0/1", "no shutdown"]
            }
        }


def create_llm_client(config: Dict[str, Any], rag_manager: Optional[RAGManager] = None) -> LLMClient:
    import os
    provider = config.get("provider", "stub")
    
    if provider == "ollama":
        model = config.get("model", "qwen2.5:14b")
        host = os.getenv("OLLAMA_HOST", config.get("host", "http://ollama:11434"))
        return OllamaClient(model=model, host=host, rag_manager=rag_manager)
        
    return StubLLMClient(rag_manager=rag_manager)