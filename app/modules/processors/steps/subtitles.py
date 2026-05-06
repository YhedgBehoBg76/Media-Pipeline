import os
import subprocess
import logging
import uuid

from pathlib import Path
from faster_whisper import WhisperModel

from app.modules.processors.base import ProcessingStrategy

logger = logging.getLogger(__name__)

_model = None

def _get_model():
    global _model
    if _model is None:
        _model = WhisperModel("tiny", device="cpu", compute_type="int8")
    return _model

class ApplySubtitlesStep(ProcessingStrategy):

    @property
    def name(self) -> str:
        return "apply_subtitles"

    def process(self, input_path: str, output_path: str, params: dict = None) -> bool:
        if params is None:
            params = {}

        language = params.get("language", None)

        # Временные файлы
        tmp_audio = str((Path(input_path).parent / Path(f"{Path(input_path).stem}_audio_{uuid.uuid4().hex}.wav")).resolve())
        tmp_srt = str((Path(input_path).parent / Path(f"{Path(input_path).stem}_subtitles_{uuid.uuid4().hex}.srt")).resolve())

        try:
            self._extract_audio(input_path, tmp_audio)

            # 2. Транскрибация
            model = _get_model()
            segments, info = model.transcribe(tmp_audio, language=language)
            # Логирование (опционально)
            # 3. Генерация SRT
            srt_content = self._generate_srt(segments)

            # 4. Сохранение SRT во временный файл
            with open(tmp_srt, mode="w", encoding="utf-8") as f:
                f.write(srt_content)

            # 5. Наложение субтитров на видео (ultrafast для скорости)
            self._burn_subtitles(input_path, tmp_srt, output_path)

            return True

        except Exception as e:
            # Не подавляем исключение – даем упасть наверх, чтобы pipeline поймал
            raise Exception(f"[SubtitlesStep] Failed: {e}")

        finally:
            # Чистка временных файлов (можно вынести в отдельный метод)
            for tmp_file in (tmp_audio, tmp_srt):
                if tmp_file and os.path.exists(tmp_file):
                    try:
                        os.remove(tmp_file)
                    except Exception:
                        pass


    def _generate_srt(self, segments) -> str:
        """Формирует SRT-строку из сегментов faster-whisper."""
        srt_lines = []
        for i, segment in enumerate(segments, start=1):
            start = self._format_time(segment.start)
            end = self._format_time(segment.end)
            text = segment.text.strip()
            srt_lines.append(f"{i}\n{start} --> {end}\n{text}\n")
        return "\n".join(srt_lines)


    @staticmethod
    def _extract_audio(input_path: str, output_audio: str) -> None:
#ffmpeg -fflags +genpts+igndts -err_detect ignore_err -i test_output.mp4 -vn -acodec pcm_s16le -ar 16000 -ac 1 -map 0:a:0 -y test_audio.wav
        cmd = [
            "ffmpeg",
            "-fflags", "+genpts+igndts",  # перегенерировать временные метки, игнорировать битые DTS
            "-err_detect", "ignore_err",  # не падать при битых пакетах
            "-i", input_path,
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            "-y",
            output_audio
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            # Если даже с игнорированием ошибок не вышло – тогда только бросаем исключение
            raise Exception(f"Audio extraction failed: {result.stderr}")


    @staticmethod
    def _format_time(seconds: float) -> str:
        """Конвертирует секунды в формат SRT HH:MM:SS,mmm."""
        ms = int(seconds * 1000)
        h = ms // 3600000
        m = (ms % 3600000) // 60000
        s = (ms % 60000) // 1000
        ms_last = ms % 1000
        return f"{h:02d}:{m:02d}:{s:02d},{ms_last:03d}"


    @staticmethod
    def _burn_subtitles(video_path: str, srt_path: str, output_path: str) -> None:
        """Вшивает субтитры в видео с помощью ffmpeg (ultrafast preset)."""
        cmd = [
            "ffmpeg",
            "-i", video_path,
            "-vf", f"subtitles={srt_path}:force_style='FontSize=20,PrimaryColour=&H00FFFFFF'",
            "-c:a", "copy",        # аудио без перекодирования
            "-preset", "ultrafast",  # максимальная скорость
            "-crf", "23",           # приемлемое качество
            "-y",
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise Exception(f"Burning subtitles failed: {result.stderr}")
