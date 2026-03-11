import subprocess
from app.modules.processors.base import ProcessingStrategy

class SimpleCutStrategy(ProcessingStrategy):
    def process(self, video_path: str, output_path: str) -> bool:
        # Вырезаем 30 секунд с начала и делаем 9:16
        cmd = [
            "ffmpeg", "-i", video_path,
            "-ss", "00:00:00", "-t", "00:00:30",
            "-vf", "crop=ih*(9/16):ih",
            "-c:a", "copy",
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True)
        return result.returncode == 0