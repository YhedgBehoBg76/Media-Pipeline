from abc import ABC, abstractmethod
from typing import List, Dict

class SourceAdapter(ABC):
    @abstractmethod
    def get_new_content(self, config: dict) -> List[Dict]:
        """
        Возвращает список новых видео для обработки.

        Returns:
            [
                {
                    "url": str,
                    "source_type": str,

                    "metadata":
                    {
                        #обязательные
                        "title": str,
                        "description": str,
                        "tags": list[str], # контентные теги: cartoon, spongebob

                        #опциональные
                        "yt_video_id": str
                        "yt_channel_id": str
                    }
                }
            ]
        """
        pass

    @abstractmethod
    def validate_config(self, config: dict) -> bool:
        """Проверяет валидность конфигурации источника"""
        pass
