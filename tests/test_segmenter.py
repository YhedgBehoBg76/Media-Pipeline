import os
import subprocess
import pytest
from unittest.mock import patch, MagicMock, call
from pathlib import Path

from app.modules.processors.segmenter import FixedDurationSegmenter


class TestFixedDurationSegmenter:
    @pytest.fixture
    def segmenter(self):
        return FixedDurationSegmenter(default_duration=60, default_overlap=5)

    @pytest.fixture
    def dummy_input(self, tmp_path):
        """Создаёт временный пустой файл для эмуляции входного видео."""
        p = tmp_path / "test_video.mp4"
        p.touch()
        return str(p)

    # ==================== 1. Валидация входных данных ====================
    def test_split_invalid_duration_raises(self, segmenter, dummy_input, tmp_path):
        with pytest.raises(ValueError, match="duration должно быть числом > 0"):
            segmenter.split(dummy_input, {"duration": -5, "output_dir": str(tmp_path)})

    def test_split_invalid_overlap_raises(self, segmenter, dummy_input, tmp_path):
        with pytest.raises(ValueError, match="overlap.*<.*duration"):
            segmenter.split(dummy_input, {"overlap": 70, "output_dir": str(tmp_path)})

    def test_split_missing_file_raises(self, segmenter, tmp_path):
        with pytest.raises(FileNotFoundError):
            segmenter.split("/non/existent/file.mp4", {"output_dir": str(tmp_path)})

    def test_split_creates_output_dir_if_missing(self, segmenter, dummy_input, tmp_path):
        out_dir = tmp_path / "nested" / "output"
        with patch.object(segmenter, '_probe_duration', return_value=100.0), \
             patch.object(segmenter, '_run_ffmpeg_segment', return_value=False):  # fail fast
            segmenter.split(dummy_input, {"output_dir": str(out_dir)})
        assert out_dir.exists()

    # ==================== 2. Чистая логика расчёта таймингов ====================
    def test_calculate_timing_points_standard_flow(self):
        # 180 сек, чанки 60 сек, оверлап 5 сек -> шаг 55
        points = FixedDurationSegmenter._calculate_timing_points(
            total_duration=180.0, duration=60.0, overlap=5.0, min_chunk=5.0, max_segments=None
        )
        expected = [(0.0, 60.0), (55.0, 60.0), (110.0, 60.0), (165.0, 15.0)]
        assert points == expected

    def test_calculate_timing_points_respects_max_segments(self):
        points = FixedDurationSegmenter._calculate_timing_points(
            total_duration=180.0, duration=60.0, overlap=0.0, min_chunk=1.0, max_segments=2
        )
        assert len(points) == 2
        assert points == [(0.0, 60.0), (60.0, 60.0)]

    def test_calculate_timing_points_drops_trailing_chunk_below_min_chunk(self):
        # 62 сек видео, чанки 30. Остаток 2 сек < min_chunk(5) -> отбрасывается
        points = FixedDurationSegmenter._calculate_timing_points(
            total_duration=62.0, duration=30.0, overlap=0.0, min_chunk=5.0, max_segments=None
        )
        assert len(points) == 2
        assert points == [(0.0, 30.0), (30.0, 30.0)]

    # ==================== 3. Интеграция split (с моками) ====================
    @patch('app.modules.processors.segmenter.uuid.uuid4')
    @patch.object(FixedDurationSegmenter, '_run_ffmpeg_segment', return_value=True)
    @patch.object(FixedDurationSegmenter, '_probe_duration', return_value=120.0)
    def test_split_success_returns_correct_paths(self, mock_probe, mock_ffmpeg, mock_uuid, segmenter, dummy_input, tmp_path):
        mock_uuid.return_value.hex = "abc123def"
        out_dir = str(tmp_path)
        result = segmenter.split(dummy_input, {"output_dir": out_dir, "duration": 60, "overlap": 0})

        assert len(result) == 2
        assert result[0].endswith("test_video_abc123de_seg_00.mp4")
        assert result[1].endswith("test_video_abc123de_seg_01.mp4")
        assert all(os.path.isabs(p) for p in result)

    @patch.object(FixedDurationSegmenter, '_cleanup_segments')
    @patch.object(FixedDurationSegmenter, '_run_ffmpeg_segment', side_effect=[True, False, True])
    @patch.object(FixedDurationSegmenter, '_probe_duration', return_value=180.0)
    def test_split_cleans_up_and_returns_empty_on_ffmpeg_failure(
        self, mock_probe, mock_ffmpeg, mock_cleanup, segmenter, dummy_input, tmp_path
    ):
        # Сломается на 2-м сегменте
        result = segmenter.split(dummy_input, {"output_dir": str(tmp_path), "duration": 60, "overlap": 0})

        assert result == []
        mock_cleanup.assert_called_once()
        # Убедимся, что cleanup вызвался только с 1 успешным сегментом
        cleaned_paths = mock_cleanup.call_args[0][0]
        assert len(cleaned_paths) == 1

    # ==================== 4. Тесты обёрток FFmpeg ====================
    def test_probe_duration_parses_ffprobe_output_correctly(self, tmp_path):
        dummy = str(tmp_path / "vid.mp4")
        Path(dummy).touch()

        mock_result = MagicMock()
        mock_result.stdout = "120.543\n"
        mock_result.returncode = 0

        with patch('app.modules.processors.segmenter.subprocess.run', return_value=mock_result) as mock_run:
            duration = FixedDurationSegmenter._probe_duration(dummy)

        assert duration == 120.543
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "ffprobe" in cmd[0]
        assert dummy in cmd
        assert "format=duration" in cmd

    def test_run_ffmpeg_segment_builds_correct_command(self, tmp_path):
        dummy_in = str(tmp_path / "in.mp4")
        dummy_out = str(tmp_path / "out.mp4")
        Path(dummy_in).touch()

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch('app.modules.processors.segmenter.subprocess.run', return_value=mock_result) as mock_run:
            success = FixedDurationSegmenter._run_ffmpeg_segment(dummy_in, dummy_out, 10.5, 30.0)

        assert success is True
        cmd = mock_run.call_args[0][0]
        assert cmd == [
            "ffmpeg", "-ss", "10.5", "-i", dummy_in, "-t", "30.0",
            "-c:v", "copy", "-c:a", "copy",
            "-avoid_negative_ts", "make_zero", "-y", dummy_out
        ]

    def test_run_ffmpeg_segment_returns_false_on_error(self, tmp_path):
        dummy_in = str(tmp_path / "in.mp4")
        dummy_out = str(tmp_path / "out.mp4")
        Path(dummy_in).touch()

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Error: invalid data found"

        with patch('app.modules.processors.segmenter.subprocess.run', return_value=mock_result):
            success = FixedDurationSegmenter._run_ffmpeg_segment(dummy_in, dummy_out, 0.0, 10.0)

        assert success is False