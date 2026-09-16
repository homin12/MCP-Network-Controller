from typing import List, Dict, Any, Optional
from loguru import logger

from .vector_store import VectorStore
from models import RAGContext, Document


class RAGRetriever:
    """
    Ищет документы и формирует контекст для ИИ-агента.
    """
    
    def __init__(self, vector_store: VectorStore, max_documents: int = 5):
        self.vector_store = vector_store
        self.max_documents = max_documents
    
    def retrieve(self, query: str, filter_metadata: Dict[str, Any] = None) -> RAGContext:
        """
        Ищет релевантные документы.
        """
        logger.info(f"RAG semantic search: {query[:50]}...")
        
        results = self.vector_store.search(
            query=query,
            n_results=self.max_documents,
            filter_metadata=filter_metadata
        )
        
        if not results:
            logger.warning("No results in the vector index.")
            return RAGContext(
                documents=[],
                query=query,
                combined_context="",
                confidence=0.0
            )
        
        documents = []
        for result in results:
            doc = Document(
                id=result["id"],
                content=result["content"],
                metadata=result["metadata"]
            )
            documents.append(doc)
        
        combined_context = self._build_context(documents)
        
        avg_distance = sum(r["distance"] for r in results) / len(results)
        confidence = max(0.0, 1.0 - min(avg_distance, 1.0))
        
        logger.info(f"Retrieved {len(documents)} documents. RAG confidence index: {confidence:.2f}")
        
        return RAGContext(
            documents=documents,
            query=query,
            combined_context=combined_context,
            confidence=confidence
        )
    
    def _build_context(self, documents: List[Document]) -> str:
        """
        Формирует контекст из документов.
        """
        if not documents:
            return ""
        
        context_parts = []
        for i, doc in enumerate(documents, 1):
            metadata_str = ""
            if doc.metadata:
                category = doc.metadata.get("category", "")
                device_type = doc.metadata.get("device_type", "")
                if category:
                    metadata_str += f"[{category}] "
                if device_type:
                    metadata_str += f"[{device_type}] "
            
            context_parts.append(f"Document №{i} {metadata_str}\n{doc.content}")
        
        return "\n\n".join(context_parts)
    
    def retrieve_for_command_generation(self, intent: str, devices: List[str]) -> RAGContext:
        """
        Поиск для генерации CLI команд.
        """
        enhanced_query = f"{intent}. Устройства: {', '.join(devices)}. Требуются команды Cisco IOS."
        
        filter_metadata = {
            "$or": [
                {"category": "show"},
                {"category": "configure"}
            ]
        }
        
        return self.retrieve(enhanced_query, filter_metadata)
    
    def retrieve_for_analysis(self, intent: str) -> RAGContext:
        """
        Поиск для анализа намерений.
        """
        filter_metadata = {
            "$or": [
                {"category": "rfc"},
                {"category": "best_practice"}
            ]
        }
        
        return self.retrieve(intent, filter_metadata)
