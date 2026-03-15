
from typing import Dict, Type, List, Union
from app.modules.processors.base import ProcessingStrategy
from app.modules.processors.pipeline import ProcessingPipeline
from app.modules.processors.steps.simple_cut import SimpleCutStep


class ProcessorFactory:
    """Фабрика для создания процессоров видео (поддерживает pipeline)"""

    _steps: Dict[str, Type[ProcessingStrategy]] = {
        "simple_cut": SimpleCutStep,
        # "subtitles": SubtitlesStep
    }

    @classmethod
    def get_processor(cls, strategy_config: Union[str, List[str]]) -> ProcessingStrategy:
        """
        Создаёт процессор по конфигурации стратегии.

        Args:
            strategy_config:
                - Строка: "simple_cut" (одиночный шаг)
                - Список: ["simple_cut", "subtitles"] (пайплайн)

        Returns:
            Экземпляр ProcessingStrategy или ProcessingPipeline

        Raises:
            ValueError: Если стратегия не поддерживается
        """

        if isinstance(strategy_config, str):
            return cls._create_step(strategy_config)

        if isinstance(strategy_config, list):
            steps = [cls._create_step(step_name) for step_name in strategy_config]
            return ProcessingPipeline(steps)

        raise ValueError(f"Invalid strategy config type: {type(strategy_config)}")

    @classmethod
    def _create_step(cls, step_name: str) -> ProcessingStrategy:
        """Создаёт отдельный шаг обработки"""
        step_class = cls._steps.get(step_name.lower())

        if not step_class:
            supported = ", ".join(cls._steps.keys())
            raise ValueError(
                f"Unknown step: '{step_name}'. "
                f"Supported steps: {supported}"
            )

        return step_class()

    @classmethod
    def get_available_steps(cls) -> list:
        return list(cls._steps.keys())

