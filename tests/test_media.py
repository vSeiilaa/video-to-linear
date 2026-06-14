import subprocess

from src.media import _ffmpeg_error_detail


def test_error_detail_decodes_stderr_tail():
    exc = subprocess.CalledProcessError(
        1, ["ffmpeg"], stderr=b"line1\nline2\nreal ffmpeg error here\n"
    )
    detail = _ffmpeg_error_detail(exc)
    assert "real ffmpeg error here" in detail


def test_error_detail_limits_to_last_lines():
    many = "\n".join(f"l{i}" for i in range(20)).encode()
    exc = subprocess.CalledProcessError(1, ["ffmpeg"], stderr=many)
    detail = _ffmpeg_error_detail(exc)
    assert "l19" in detail
    assert "l0" not in detail  # early noise dropped


def test_error_detail_without_stderr():
    exc = subprocess.TimeoutExpired(["ffmpeg"], 300)
    # Should not raise and should return a string representation
    assert isinstance(_ffmpeg_error_detail(exc), str)
