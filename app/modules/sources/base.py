from abc import ABC, abstractmethod
from typing import List, Dict

class SourceAdapter(ABC):
    @abstractmethod
    def get_new_content(self, config: dict) -> List[Dict]:
        """Возвращает список новых видео для обработки"""
        pass
