import subprocess
from app.modules.processors.base import ProcessingStrategy


class SimpleCutStep(ProcessingStrategy):
    DEFAULT_DURATION = 55

    @property
    def name(self) -> str:
        return "simple_cut"

    def process(self, input_path: str, output_path: str, params: dict = None) -> bool:
        """
        кропает в 9:16.
        """
        # ffmpeg -fflags +genpts+igndts -err_detect ignore_err -i /tmp/media/1/segments/source_media_id_1_c9d53268_seg_0.mp4 -vf "crop=ih*(9/16):ih" -c:v libx264 -preset ultrafast -crf 23 -c:a aac -b:a 128k -movflags +faststart -y /tmp/media/1/test_output.mp4
        cmd = [
            "ffmpeg",
            "-fflags", "+genpts+igndts",  # починить временные метки
            "-err_detect", "ignore_err",  # игнорировать битые пакеты
            "-i", input_path,
            "-vf", "crop=ih*(9/16):ih",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            "-y",
            output_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise Exception(f"[SimpleCutStep] FFmpeg error: {result.stderr}")

        return True
