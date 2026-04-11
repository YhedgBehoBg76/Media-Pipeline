import subprocess
from app.modules.processors.base import ProcessingStrategy


class SimpleCutStep(ProcessingStrategy):
    DEFAULT_DURATION = 55

    @property
    def name(self) -> str:
        return "simple_cut"

    def process(self, input_path: str, output_path: str, params: dict = None) -> bool:
        """
        Обрезает видео до указанной длительности и кропает в 9:16.
        """

        cmd = [
            "ffmpeg",
            "-i", input_path,
            "-vf", "crop=ih*(9/16):ih",
            "-c:a", "copy",
            "-y",
            output_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise Exception(f"[SimpleCutStrategy] FFmpeg error: {result.stderr}")

        return True
