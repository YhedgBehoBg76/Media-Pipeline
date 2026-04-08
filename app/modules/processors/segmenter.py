import os
import uuid
import logging
import subprocess
from pathlib import Path
from typing import Dict, List, Any


logger = logging.getLogger(__name__)


class FixedDurationSegmenter:
    """
    Препроцессор для разбиения видеофайла на сегменты заданной длительности.

    Использует stream copy (без перекодирования) для максимальной скорости.
    Предназначен для запуска ДО основного ProcessingPipeline.

    Пример:
        segmenter = FixedDurationSegmenter(default_duration=55, default_overlap=3)
        paths = segmenter.split("input.mp4", {"overlap": 5, "output_dir": "/tmp"})
    """

    def __init__(self, default_duration:int = 55, default_overlap: int = 0):
        """
        Args:
            default_duration: Целевая длительность сегмента (сек). По умолчанию 55.
            default_overlap: Перекрытие между соседними сегментами (сек). По умолчанию 0.
        """
        self.default_duration = default_duration
        self.default_overlap = default_overlap

    def split(self, input_path: str, params: dict[str, Any]):
        """
        Нарезает видео на сегменты по заданным параметрам.

        Args:
            input_path: Абсолютный путь к исходному видеофайлу.
            params:

                duration (int): Длительность сегмента. По умолч. 55.

                overlap (int): Перекрытие между сегментами. 0 <= overlap < duration.

                output_dir (str): Директория для сохранения. По умолч. /tmp/media.

                min_chunk (int): Мин. длительность последнего сегмента. Если остаток меньше этого значения, он отбрасывается. По умолч. 5.

                max_segments (int | None): Лимит количества создаваемых сегментов.

        Returns:
            Список абсолютных путей к успешно созданным сегментам.
            Возвращает пустой список при любой ошибке выполнения (fail-fast).

        Raises:
            ValueError: При некорректных входных параметрах.
            FileNotFoundError: Если входной файл не существует.
            RuntimeError: При невозможности создать output_dir или прочитать метаданные.
        """
        duration = params.get("duration", self.default_duration)
        overlap = params.get("overlap", self.default_overlap)
        output_dir = params.get("output_dir", "/tmp/media")
        min_chunk = params.get("min_chunk", 5)
        max_segments = params.get("max_segments")

        if not isinstance(duration, (int, float)) or duration <= 0:
            raise ValueError("duration должно быть числом > 0")
        if not isinstance(overlap, (int, float)) or not (0 <= overlap < duration):
            raise ValueError(f"overlap должен быть 0 <= overlap < duration={duration}, но overlap={overlap}")
        if not os.path.isfile(input_path):
            raise FileNotFoundError(f"Входной файл не найден: {input_path}")

        Path(output_dir).mkdir(parents=True, exist_ok=True)

        total_duration = self._probe_duration(input_path)

        timing_points = self._calculate_timing_points(
            total_duration=total_duration,
            duration=duration,
            overlap=overlap,
            min_chunk=min_chunk,
            max_segments=max_segments
        )

        if not timing_points:
            logger.warning(f"Видео '{input_path}' короче min_chunk или duration. Сегменты не созданы")
            return []

        segments = []
        task_id = uuid.uuid4().hex[:8]
        stem = Path(input_path).stem

        for idx, (start, dur) in enumerate(timing_points):
            out_name = f"{stem}_{task_id}_seg_{idx:02d}.mp4"
            out_path = os.path.join(output_dir, out_name)

            if not self._run_ffmpeg_segment(input_path, out_path, start, dur):
                logger.error("FFmpeg упал на сегменте %d (start=%.2f). Откат изменений.", idx, start)
                self._cleanup_segments(segments)
                return []

            segments.append(out_path)

        logger.info("Успешно создано %d сегментов для %s", len(segments), os.path.basename(input_path))
        return segments

    @staticmethod
    def _probe_duration(input_path: str) -> float:
        """Возвращает длительность видео в секундах через ffprobe."""
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            input_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, check=True)

        return float(result.stdout.strip())

    @staticmethod
    def _calculate_timing_points(
            total_duration: float,
            duration: float,
            overlap: float,
            min_chunk: float,
            max_segments: int | None
    ) -> list[tuple[float, float]]:
        """
        Вычисляет список кортежей (start_time, chunk_duration).
        """
        points = []
        start = 0.0
        step = duration - overlap
        idx = 0

        while start + min_chunk <= total_duration:
            if max_segments is not None and idx >= max_segments:
                break

            chunk = min(duration, total_duration-start)
            points.append((start, chunk))

            start += step
            idx += 1

        return points

    @staticmethod
    def _run_ffmpeg_segment(input_path: str, output_path: str, start: float, duration: float) -> bool:
        """Запускает FFmpeg для вырезки одного сегмента. Возвращает True при успехе."""
        cmd = [
            "ffmpeg",
            "-ss", str(start),
            "-i", input_path,
            "-t", str(duration),
            "-c:v", "copy", "-c:a", "copy",
            "-avoid_negative_ts", "make_zero",
            "-y",
            output_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, check=True)

        if result.returncode != 0:
            logger.error("FFmpeg error (code %d): %s", result.returncode, result.stderr.strip())
            return False
        return True

    @staticmethod
    def _cleanup_segments(segments: list[str]) -> None:
        """Атомарно удаляет частично созданные сегменты при сбое."""
        for path in segments:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError as exc:
                logger.warning("Не удалось удалить временный сегмент %s: %s", path, exc)


