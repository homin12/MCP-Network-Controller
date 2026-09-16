import os
import shutil
from typing import Dict, Any, List, Optional
from loguru import logger

from .vector_store import VectorStore
from .retriever import RAGRetriever
from .document_loader import DocumentLoader
from models import RAGContext


class RAGManager:
    def __init__(self, persist_directory: str = "./rag_data",
                 collection_name: str = "network_commands",
                 knowledge_data_dir: str = "./rag/data",
                 project_id: str = None,
                 auto_load: bool = True,
                 force_rebuild: bool = False):
        
        self.persist_directory = persist_directory
        self.collection_name = collection_name
        self.project_id = project_id
        
        if force_rebuild and os.path.exists(persist_directory):
            try:
                shutil.rmtree(persist_directory)
                logger.info(f"RAG database removed")
            except Exception as e:
                logger.warning(f"Failed to delete the database directory: {e}")
        
        try:
            self.vector_store = VectorStore(collection_name, persist_directory)
            self.retriever = RAGRetriever(self.vector_store)
            
            self.document_loader = DocumentLoader(knowledge_data_dir)
            
            if auto_load:
                self.load_documents()
            
            logger.info("RAG Manager successfully initialized.")
        except Exception as e:
            logger.error(f"Critical error during RAG Manager initialization: {e}")
            raise
    
    def load_documents(self):
        """
        Парсит внешние файлы знаний и загружает их в векторное хранилище.
        """       

        collection_info = self.vector_store.get_collection_info()
        if collection_info.get("count", 0) > 0:
            logger.info(f"The database already contains {collection_info['count']} vectors. Skipping re-indexing.")
            return
            
        # Если база пуста то запускаем лоадер.
        documents = self.document_loader.load_all_documents(self.project_id)
        
        if documents:
            logger.info(f"Starting the vectorization process for {len(documents)} documents...")
            self.vector_store.add_documents(documents)
            logger.info(f"The RAG vector index successfully built.")
        else:
            logger.warning("The loader not return any documents. Indexing cancelled.")
    
    def get_context(self, query: str, context_type: str = "all") -> RAGContext:
        """
        Получает контекст для запроса.
        """
        filter_metadata = {}
        
        if context_type == "commands":
            filter_metadata = {
                "$or": [
                    {"category": "show"},
                    {"category": "configure"}
                ]
            }
        elif context_type == "analysis":
            filter_metadata = {
                "$or": [
                    {"category": "rfc"},
                    {"category": "best_practice"}
                ]
            }
        elif context_type == "topology":
            filter_metadata = {"category": "topology"}
            
        return self.retriever.retrieve(query, filter_metadata if filter_metadata else None)
    
    def get_context_for_command_generation(self, intent: str, devices: List[str]) -> RAGContext:
        """
        Возвращает контекст синтаксиса команд.
        """
        return self.retriever.retrieve_for_command_generation(intent, devices)
    
    def get_context_for_analysis(self, intent: str) -> RAGContext:
        """
        Возвращает теоретический контекст.
        """
        return self.retriever.retrieve_for_analysis(intent)
    
    def add_document(self, content: str, metadata: Dict[str, Any] = None):
        """
        Добавление нового документа в базу знаний.
        """
        import uuid
        doc_id = f"doc_dyn_{uuid.uuid4().hex[:8]}"
        self.vector_store.add_document(doc_id, content, metadata)
        logger.info(f"Document added to the index with ID: {doc_id}")
    
    def get_collection_info(self) -> Dict[str, Any]:
        return self.vector_store.get_collection_info()
    
    def clear(self):
        """Очистка коллекции векторов."""
        try:
            self.vector_store.reset()
            logger.info("The RAG vector collection cleared.")
        except Exception as e:
            logger.error(f"Error clearing storage: {e}")
