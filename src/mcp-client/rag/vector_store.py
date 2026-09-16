import os
import json
from typing import List, Dict, Any, Optional
from loguru import logger
import chromadb
from chromadb.config import Settings
from chromadb.utils.embedding_functions import OllamaEmbeddingFunction


class VectorStore:
    """
    Векторное хранилище на основе ChromaDB.
    """
    
    def __init__(self, collection_name: str = "network_commands", 
                 persist_directory: str = "./rag_data",
                 ollama_host: str = "http://ollama:11434",
                 embedding_model: str = "nomic-embed-text"):
        
        self.collection_name = collection_name
        self.persist_directory = persist_directory
        os.makedirs(persist_directory, exist_ok=True)
        
        self.embedding_function = OllamaEmbeddingFunction(
            url=f"{ollama_host}/api/embeddings",
            model_name=embedding_model
        )
        logger.info(f"The RAG embedding pipeline is configured for the model: {embedding_model}")
        
        try:
            self.client = chromadb.PersistentClient(
                path=persist_directory,
                settings=Settings(
                    anonymized_telemetry=False,
                    allow_reset=True
                )
            )
            logger.info(f"ChromaDB client initialized")
        except Exception as e:
            logger.error(f"ChromaDB initialization error: {e}")
            raise
        
        self.collection = self._get_or_create_collection()
        logger.info(f"Vector store initialized: {collection_name}")
    
    def _get_or_create_collection(self):
        try:
            collection = self.client.get_collection(
                name=self.collection_name, 
                embedding_function=self.embedding_function
            )
            logger.info(f"Collection '{self.collection_name}' found (docs: {collection.count()})")
            return collection
        except Exception:
            collection = self.client.create_collection(
                name=self.collection_name,
                embedding_function=self.embedding_function,
                metadata={"hnsw:space": "cosine"}
            )
            logger.info(f"Collection '{self.collection_name}' created with the cosine metric")
            return collection
    
    def add_document(self, doc_id: str, content: str, metadata: Dict[str, Any] = None):
        try:
            self.collection.add(
                documents=[content],
                metadatas=[metadata or {}],
                ids=[doc_id]
            )
            logger.debug(f"Document added: {doc_id}")
        except Exception as e:
            logger.error(f"Error adding document {doc_id}: {e}")
    
    def add_documents(self, documents: List[Dict[str, Any]]):
        try:
            ids = []
            contents = []
            metadatas = []
            
            for doc in documents:
                ids.append(doc["id"])
                contents.append(doc["content"])
                metadatas.append(doc.get("metadata", {}))
            
            self.collection.add(
                documents=contents,
                metadatas=metadatas,
                ids=ids
            )
            logger.info(f"Added {len(documents)} documents to the vector index.")
        except Exception as e:
            logger.error(f"Error adding documents: {e}")
    
    def search(self, query: str, n_results: int = 5, filter_metadata: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        try:
            where_filter = filter_metadata or {}
            
            results = self.collection.query(
                query_texts=[query],
                n_results=n_results,
                where=where_filter if where_filter else None
            )
            
            formatted_results = []
            if results and results['ids'] and len(results['ids']) > 0:
                for i in range(len(results['ids'][0])):
                    formatted_results.append({
                        "id": results['ids'][0][i],
                        "content": results['documents'][0][i] if results['documents'] and results['documents'][0] else "",
                        "metadata": results['metadatas'][0][i] if results['metadatas'] and results['metadatas'][0] else {},
                        "distance": results['distances'][0][i] if results['distances'] and results['distances'][0] else 0
                    })
            
            return formatted_results
            
        except Exception as e:
            logger.error(f"Vector search error: {e}")
            return []
    
    def delete_collection(self):
        try:
            self.client.delete_collection(self.collection_name)
            logger.info(f"Collection '{self.collection_name}' deleted")
        except Exception as e:
            logger.error(f"Error deleting collection: {e}")
    
    def get_collection_info(self) -> Dict[str, Any]:
        try:
            count = self.collection.count()
            return {
                "name": self.collection_name,
                "count": count,
                "metadata": self.collection.metadata
            }
        except Exception as e:
            logger.error(f"Error retrieving information: {e}")
            return {"name": self.collection_name, "count": 0}
    
    def reset(self):
        try:
            self.delete_collection()
            self.collection = self._get_or_create_collection()
            logger.info(f"Storage reset")
        except Exception as e:
            logger.error(f"Storage reset error: {e}")
