from typing import Dict, Type
from app.modules.sources.base import SourceAdapter
from app.modules.sources.youtube import YouTubeAdapter
#from app.modules.sources.filesystem import FilesystemAdapter
#from app.modules.sources.twich import TwichAdapter

class SourceAdapterFactory:
    _adapters: Dict[str, Type[SourceAdapter]] = {
        "youtube": YouTubeAdapter

    }

    @classmethod
    def get_adapter(cls, source_type: str):
        """
        Создаёт и возвращает адаптер по типу источника

        Args:
            source_type: Тип источника (youtube, filesystem, twitch)

        Returns:
            Экземпляр соответствующего адаптера

        Raises:
            ValueError: Если тип источника не поддерживается
        """
        adapter_class = cls._adapters.get(source_type.lower())
        if not adapter_class:
            supported = ", ".join(cls._adapters.keys())
            raise ValueError(
                f"Unknown source type '{source_type}'"
                f"Supported sources: '{supported}'"
            )

        return adapter_class()

    @classmethod
    def get_available_types(cls) -> list:
        return list(cls._adapters.keys())
