
import os
import shutil
from typing import List
from app.modules.processors.base import ProcessingStrategy

class ProcessingPipeline(ProcessingStrategy):
    """
    Композитный паттерн: объединяет несколько стратегий обработки в цепочку.

    Пример:
        pipeline = ProcessingPipeline([
            SimpleCutStep(),
            LightEffectsStep(),
            SubtitlesStep()
        ])
        pipeline.process("input.mp4", "output.mp4", params)
    """

    def __init__(self, steps: List[ProcessingStrategy]):
        """
        Инициализирует пайплайн с списком шагов обработки.

        Args:
            steps: Список стратегий обработки в порядке выполнения
        """
        self.steps = steps

    @property
    def name(self) -> str:
        """Возвращает название пайплайна (список шагов)"""
        return "pipeline_" + "_".join([step.name for step in self.steps])

    def process(self, input_path: str, output_path: str, params: dict):
        """
        Последовательно выполняет все шаги обработки.

        Args:
            input_path: Путь к исходному видео
            output_path: Путь для финального результата
            params: Параметры обработки (передаются всем шагам)

        Returns:
            True если все шаги успешны

        Raises:
            Exception: Если любой шаг не удался
        """
        current_path = input_path
        temp_files = []

        try:
            for i, step in enumerate(self.steps):
                if i < len(self.steps) - 1:
                    temp_path = f"/tmp/media/temp_{i}_{step.name}.mp4"
                    temp_files.append(temp_path)
                    target_path = temp_path
                else:
                    target_path = output_path

                success = step.process(current_path, target_path, params)

                if not success:
                    raise Exception(f"Step '{step.name}' failed")

                current_path = target_path

            return True

        except Exception as e:
            self._cleanup_temp_files(temp_files)
            raise Exception(f"[ProcessingPipeline] pipeline failed: {e}")

        finally:
            self._cleanup_temp_files(temp_files)

    @staticmethod
    def _cleanup_temp_files(temp_files: List[str]):
        for file_path in temp_files:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception:
                pass

