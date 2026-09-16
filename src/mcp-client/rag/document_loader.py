import json
import os
from typing import List, Dict, Any
from loguru import logger
import yaml

class DocumentLoader:
    def __init__(self, data_dir: str = "./rag/data"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
    
    def _load_yaml_file(self, filename: str) -> List[Dict[str, Any]]:
        """Читает файлы знаний."""
        file_path = os.path.join(self.data_dir, filename)
        if not os.path.exists(file_path):
            logger.warning(f"Base file not found: {file_path}")
            return []
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                return data if isinstance(data, list) else []
        except Exception as e:
            logger.error(f"Error reading file {filename}: {e}")
            return []

    def load_cisco_commands(self) -> List[Dict[str, Any]]:
        """Читает справочник CLI команд."""
        return self._load_yaml_file("cisco_commands.yaml")
    
    def load_rfc_summaries(self) -> List[Dict[str, Any]]:
        """Читает выжимки из стандартов RFC."""
        return self._load_yaml_file("rfc_summaries.yaml")
    
    def load_best_practices(self) -> List[Dict[str, Any]]:
        """Читает корпоративные политики и лучшие практики."""
        return self._load_yaml_file("best_practices.yaml")
    
    def load_all_documents(self, project_id: str = None) -> List[Dict[str, Any]]:
        """Агрегирует все источники данных в единый массив для индексации."""
        documents = []
        documents.extend(self.load_cisco_commands())
        documents.extend(self.load_rfc_summaries())
        documents.extend(self.load_best_practices())
        
        logger.info(f"Loaded {len(documents)} documents from the directory {self.data_dir}")
        return documents
