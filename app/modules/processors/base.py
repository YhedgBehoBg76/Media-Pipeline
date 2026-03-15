from abc import ABC, abstractmethod
from typing import List, Dict


class ProcessingStrategy(ABC):
    """Базовый класс для всех стратегий обработки видео"""
    @abstractmethod
    def process(self, input_path: str, output_path: str, params:dict) -> bool:
        """
        Обрабатывает видео и возвращает True при успехе.

        Args:
            input_path: Путь к исходному видео
            output_path: Путь для сохранения обработанного видео
            params: Параметры обработки (длительность, формат, etc.)

        Returns:
            True если обработка успешна

        Raises:
            Exception: Если обработка не удалась
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Возвращает название стратегии (для логирования)"""
        pass
