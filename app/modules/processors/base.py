from abc import ABC, abstractmethod
from typing import List, Dict


class ProcessingStrategy(ABC):
    @abstractmethod
    def process(self, video_path: str, output_path: str) -> bool:
        """Обрабатывает видео и возвращает True/False"""
        pass