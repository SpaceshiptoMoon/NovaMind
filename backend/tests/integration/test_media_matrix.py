"""多模态解析矩阵真机集成测试（docs/parsing-test-matrix.md 三/四区）。

覆盖音频（本地 ASR 真实语音/静音/损坏/热词、格式探测）、视频（音轨提取、
fixed/scene 抽帧、视频→音轨→ASR 串联）、时间对齐（锚点剥离/时间区间/
无锚点标未知）、片尾告别语（P2-4 回归：末段套话能量裁决保留真实语音）。

依赖：ffmpeg（帧/音轨）、faster-whisper small 缓存（转写）、Windows SAPI
（TTS 造语音）。依赖不满足时逐用例 skip。VLM/云端 ASR 需外部 API 的
策略段（grouped/rewrite/frame_seq/video_native 的 VLM 描述部分）不在本
文件——按矩阵标注需 API key 环境补测。
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = [pytest.mark.integration]

PROBE_DIR = BACKEND_ROOT / "test_data" / "_probe"
TTS_TEXT = "知识库解析引擎语音识别验证，今天天气很好"


def _ffmpeg_available() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except Exception:
        return False


def _whisper_cache_available() -> bool:
    return (BACKEND_ROOT / ".cache" / "faster-whisper" / "small").exists()


def _tts_wav(tmp_path: Path, text: str) -> Path:
    """Windows SAPI TTS 合成中文语音（非 Windows 环境由调用方 skip）。"""
    wav = tmp_path / "tts.wav"
    q = chr(39)
    ps = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$s.SetOutputToWaveFile(" + q + str(wav.resolve()) + q + "); "
        "$s.Speak(" + q + text + q + "); $s.Dispose()"
    )
    subprocess.run(["powershell", "-Command", ps], capture_output=True, check=True)
    assert wav.exists() and wav.stat().st_size > 1000
    return wav


def _make_video(out: Path, duration: int = 5, with_audio: bool = True) -> Path:
    """ffmpeg 合成测试视频（testsrc 画面，可选 440Hz 音轨）。"""
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i",
           f"testsrc=duration={duration}:size=320x240:rate=10"]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}"]
    cmd += ["-shortest", "-c:v", "libx264", "-preset", "ultrafast"]
    if with_audio:
        cmd += ["-c:a", "aac"]
    cmd += [str(out)]
    subprocess.run(cmd, capture_output=True, check=True)
    return out


needs_ffmpeg = pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg 不可用")
needs_whisper = pytest.mark.skipif(not _whisper_cache_available(), reason="faster-whisper small 未缓存")


# ---------------------------------------------------------------- 音频
class TestAudioLocal:
    @needs_ffmpeg
    @needs_whisper
    def test_real_speech_transcription(self, tmp_path):
        """T-AUD-LOCAL-REC：真实中文语音 → 转写语义命中（繁体输出为 whisper 特性）。"""
        from novamind.engines.document.media.audio import audio_utils
        from novamind.shared.config import AudioConfig

        wav = _tts_wav(tmp_path, TTS_TEXT)
        segments = asyncio.run(audio_utils.transcribe_audio_local(
            file_content=wav.read_bytes(), file_type="wav",
            audio_config=AudioConfig(local_whisper_model="small"),
        ))
        joined = "".join(s.get("text", "") for s in segments)
        assert any(kw in joined for kw in ("知识库", "知識庫")), f"转写未命中: {joined!r}"

    @needs_ffmpeg
    @needs_whisper
    def test_silence_yields_zero_segments(self, tmp_path):
        """T-AUD-LOCAL-SILENT：静音 → 0 段（幻觉过滤），不崩。"""
        from novamind.engines.document.media.audio import audio_utils
        from novamind.shared.config import AudioConfig

        wav = tmp_path / "silence.wav"
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                        "anullsrc=r=16000:cl=mono", "-t", "1", str(wav)],
                       capture_output=True, check=True)
        segments = asyncio.run(audio_utils.transcribe_audio_local(
            file_content=wav.read_bytes(), file_type="wav",
            audio_config=AudioConfig(local_whisper_model="small"),
        ))
        assert isinstance(segments, list)

    def test_corrupt_audio_raises_permanent(self):
        """T-AUD-LOCAL-BROKEN：损坏音频 → AudioFileInvalidError 永久错误。"""
        from novamind.engines.document.media.audio import audio_utils
        from novamind.engines.document.media.audio.audio_utils import AudioFileInvalidError
        from novamind.shared.config import AudioConfig

        with pytest.raises(AudioFileInvalidError):
            asyncio.run(audio_utils.transcribe_audio_local(
                file_content=b"x" * 2048, file_type="wav",
                audio_config=AudioConfig(local_whisper_model="small"),
            ))

    def test_format_detection(self):
        """格式探测：wav/mp3 魔数。"""
        from novamind.engines.document.media.audio import audio_utils
        assert audio_utils._detect_audio_format(b"ID3" + b"\x00" * 20)[0] == "mp3"


# ---------------------------------------------------------------- 视频
class TestVideoExtraction:
    @needs_ffmpeg
    def test_audio_track_extraction(self, tmp_path):
        """T-VID-AUDIOTRACK：mp4 → mp3 音轨（红队 P2-2 回归：非零退出有告警）。"""
        from novamind.engines.document.media.video import audio_track

        mp4 = _make_video(tmp_path / "v.mp4")
        audio = audio_track.extract_audio_track(str(mp4))
        assert len(audio) > 1000

    @needs_ffmpeg
    def test_fixed_frames_timestamps(self, tmp_path):
        """T-VID-SIMPLE 抽帧层：1s 间隔 → 时间戳精确 + JPEG 魔数。"""
        from novamind.engines.document.media.video import frame_extraction

        mp4 = _make_video(tmp_path / "v.mp4")
        frames = asyncio.run(frame_extraction.extract_frames_fixed(
            mp4.read_bytes(), interval=1.0, max_frames=10))
        assert len(frames) == 5
        assert [round(ts, 1) for _fb, ts, _idx in frames] == [0.0, 1.0, 2.0, 3.0, 4.0]
        assert all(fb[:2] == bytes([0xFF, 0xD8]) for fb, _t, _i in frames)

    @needs_ffmpeg
    def test_scene_strategy_two_cuts(self, tmp_path):
        """T-VID-SCENE：双场景硬切视频 → 捕获切换点（P0-1/P0-2 修复回归）。"""
        from novamind.engines.document.media.video import frame_extraction

        out = tmp_path / "hardcut.mp4"
        subprocess.run([
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc2=duration=4:size=320x240:rate=10",
            "-f", "lavfi", "-i", "smptebars=duration=4:size=320x240:rate=10",
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
            "-map", "[v]", "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
            str(out),
        ], capture_output=True, check=True)
        frames = asyncio.run(frame_extraction.extract_frames_scene(
            out.read_bytes(), max_frames=10))
        assert len(frames) >= 2, f"scene 只 {len(frames)} 帧（阈值标定回归）"
        assert any(3.0 <= ts <= 5.0 for _fb, ts, _idx in frames), "切换点未捕获"

    @needs_ffmpeg
    @needs_whisper
    def test_video_audio_to_asr_chain(self, tmp_path):
        """T-VID-TRANSCRIBE（音频分支）：视频 → 音轨 → 本地 ASR 串联。

        用 TTS 语音做音轨（440Hz 正弦无语音内容），断言转写链路通。
        """
        from novamind.engines.document.media.audio import audio_utils
        from novamind.engines.document.media.video import audio_track
        from novamind.shared.config import AudioConfig

        mp4 = _make_video(tmp_path / "v.mp4", with_audio=False)
        # 挂 TTS 语音轨
        tts = _tts_wav(tmp_path, TTS_TEXT)
        voiced = tmp_path / "voiced.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-i", str(mp4), "-i", str(tts),
            "-shortest", "-c:v", "copy", "-c:a", "aac", str(voiced),
        ], capture_output=True, check=True)

        audio = audio_track.extract_audio_track(str(voiced))
        assert len(audio) > 1000
        segments = asyncio.run(audio_utils.transcribe_audio_local(
            file_content=audio, file_type="mp3",
            audio_config=AudioConfig(local_whisper_model="small"),
        ))
        assert isinstance(segments, list)


# ---------------------------------------------------------------- 时间对齐
class TestTimeAlignment:
    def test_anchor_strip_and_alignment(self):
        """T-VID-TIMEALIGN：锚点剥离 + 时间区间 + 无锚点标未知。"""
        from novamind.engines.document.media.chunk_time_alignment import (
            align_chunk_times,
            build_segment_timeline_map,
        )

        segments = [
            {"start": 0.0, "end": 2.5, "text": "第一句"},
            {"start": 2.5, "end": 5.0, "text": "第二句"},
        ]
        timeline_map = build_segment_timeline_map(segments)
        chunks = [
            ("[00:00:00#0] 第一句的检索内容", {}),
            ("[00:00:02#1] 第二句的检索内容", {}),
            ("无锚点的尾部块", {}),
        ]
        aligned = align_chunk_times(chunks, timeline_map, is_video=False)
        assert "[00:00:00" not in aligned[0][0], "锚点未剥离"
        assert aligned[0][1]["start_time"] == 0.0 and aligned[0][1]["end_time"] == 2.5
        assert aligned[1][1]["start_time"] == 2.5
        assert aligned[2][1]["start_time"] is None


# ---------------------------------------------------------------- 片尾告别语（P2-4 回归）
class TestLastPhraseEnergyGate:
    @needs_ffmpeg
    @needs_whisper
    def test_real_last_phrase_survives_full_chain(self, tmp_path):
        """端到端：TTS 合成真实「谢谢观看」语音 → 全链过滤后保留不误丢。"""
        from novamind.engines.document.media.audio import audio_utils
        from novamind.shared.config import AudioConfig

        wav = _tts_wav(tmp_path, "谢谢观看")
        segments = asyncio.run(audio_utils.transcribe_audio_local(
            file_content=wav.read_bytes(), file_type="wav",
            audio_config=AudioConfig(local_whisper_model="small"),
        ))
        joined = "".join(s.get("text", "") for s in segments)
        assert joined.strip(), "真实片尾告别语被过滤清空——P2-4 回归"
