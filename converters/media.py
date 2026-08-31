"""Audio and video conversion through FFmpeg."""

import json
import subprocess
from pathlib import Path

from engine import rule, run, Tools, ConvertError, NO_WINDOW

AUDIO_IN = ("mp3 wav flac ogg oga opus m4a m4b aac wma aiff aif aifc amr ac3 "
            "mp2 au caf w64 wv ape mka dts spx ra tta voc 8svx")

VIDEO_IN = ("mp4 m4v avi mkv mov webm flv wmv mpg mpeg mpe m2v ts mts m2ts "
            "3gp 3g2 ogv vob asf rm rmvb divx f4v mxf dv y4m")

# Codec choices per target. The bundled FFmpeg may be old, so these stick to
# encoders that have been in FFmpeg for a very long time.
AUDIO_ARGS = {
    "mp3":  ["-c:a", "libmp3lame", "-q:a", "2"],
    "wav":  ["-c:a", "pcm_s16le"],
    "flac": ["-c:a", "flac"],
    "ogg":  ["-c:a", "libvorbis", "-q:a", "5"],
    "oga":  ["-c:a", "libvorbis", "-q:a", "5"],
    "opus": ["-c:a", "libopus", "-b:a", "128k"],
    "m4a":  ["-c:a", "aac", "-b:a", "192k"],
    "aac":  ["-c:a", "aac", "-b:a", "192k"],
    "aiff": ["-c:a", "pcm_s16be"],
    "aif":  ["-c:a", "pcm_s16be"],
    "ac3":  ["-c:a", "ac3", "-b:a", "192k"],
    "wma":  ["-c:a", "wmav2", "-b:a", "192k"],
    "mp2":  ["-c:a", "mp2", "-b:a", "192k"],
    "au":   ["-c:a", "pcm_mulaw"],
    "amr":  ["-c:a", "libopencore_amrnb", "-ar", "8000", "-ac", "1", "-b:a", "12.2k"],
    "caf":  ["-c:a", "pcm_s16le"],
}

_H264 = ["-c:v", "libx264", "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p"]
_EVEN = ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2"]

VIDEO_ARGS = {
    "mp4":  _H264 + _EVEN + ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"],
    "m4v":  _H264 + _EVEN + ["-c:a", "aac", "-b:a", "192k"],
    "mkv":  _H264 + _EVEN + ["-c:a", "libvorbis", "-q:a", "5"],
    "mov":  _H264 + _EVEN + ["-c:a", "aac", "-b:a", "192k"],
    "ts":   _H264 + _EVEN + ["-c:a", "aac", "-b:a", "128k"],
    "flv":  _H264 + _EVEN + ["-c:a", "aac", "-b:a", "128k", "-ar", "44100"],
    "avi":  ["-c:v", "mpeg4", "-qscale:v", "4", "-c:a", "libmp3lame", "-q:a", "3"],
    "webm": ["-c:v", "libvpx", "-b:v", "1500k", "-c:a", "libvorbis", "-q:a", "5"],
    "ogv":  ["-c:v", "libtheora", "-q:v", "7", "-c:a", "libvorbis", "-q:a", "5"],
    "wmv":  ["-c:v", "wmv2", "-b:v", "2000k", "-c:a", "wmav2", "-b:a", "192k"],
    "mpg":  ["-c:v", "mpeg2video", "-qscale:v", "4", "-c:a", "mp2", "-b:a", "192k"],
    "mpeg": ["-c:v", "mpeg2video", "-qscale:v", "4", "-c:a", "mp2", "-b:a", "192k"],
    "3gp":  ["-c:v", "libx264", "-profile:v", "baseline", "-level", "3.0",
             "-vf", "scale=352:288", "-c:a", "aac", "-ar", "8000", "-ac", "1", "-b:a", "32k"],
}

AUDIO_OUT = " ".join(AUDIO_ARGS)
VIDEO_OUT = " ".join(VIDEO_ARGS)


def _ff(args):
    if not Tools.ffmpeg:
        raise ConvertError("FFmpeg not found")
    return run([Tools.ffmpeg, "-y", "-nostdin", "-loglevel", "error"] + args)


def _has_video(src):
    """True if the file carries a real video stream (not just cover art)."""
    if not Tools.ffprobe:
        return True
    try:
        txt = subprocess.run(
            [Tools.ffprobe, "-v", "quiet", "-print_format", "json",
             "-show_streams", "-select_streams", "v", str(src)],
            stdout=subprocess.PIPE, creationflags=NO_WINDOW, timeout=60,
        ).stdout.decode("utf-8", "replace")
        for s in json.loads(txt or "{}").get("streams", []):
            if s.get("disposition", {}).get("attached_pic"):
                continue
            if (s.get("avg_frame_rate") or "0/0") not in ("0/0", "0/1"):
                return True
        return False
    except Exception:
        return True


@rule(AUDIO_IN + " " + VIDEO_IN, AUDIO_OUT, need=("ffmpeg",), cost=5, label="audio")
def to_audio(src, out, dst):
    args = ["-i", str(src), "-vn", "-map_metadata", "0"]
    args += AUDIO_ARGS[dst] + ["-strict", "-2", str(out)]
    _ff(args)


@rule(VIDEO_IN, VIDEO_OUT, need=("ffmpeg",), cost=5, label="video")
def to_video(src, out, dst):
    args = ["-i", str(src)] + VIDEO_ARGS[dst]
    if not _has_video(src):
        raise ConvertError("that file has no video track - pick an audio format instead")
    args += ["-strict", "-2", str(out)]
    _ff(args)


@rule(VIDEO_IN, "gif", need=("ffmpeg",), cost=6, label="video to gif")
def to_gif(src, out, dst):
    vf = "fps=12,scale=480:-1:flags=lanczos"
    try:                                    # two-pass palette, much better colours
        pal = Path(out).with_suffix(".palette.png")
        _ff(["-i", str(src), "-vf", vf + ",palettegen", str(pal)])
        _ff(["-i", str(src), "-i", str(pal), "-lavfi",
             vf + " [x]; [x][1:v] paletteuse", str(out)])
        pal.unlink(missing_ok=True)
    except ConvertError:
        _ff(["-i", str(src), "-vf", vf, str(out)])


@rule(VIDEO_IN, "png jpg jpeg bmp webp tif tiff", need=("ffmpeg",), cost=9,
      label="video frame")
def grab_frame(src, out, dst):
    """Single representative frame - handy as a thumbnail or poster image."""
    try:
        _ff(["-i", str(src), "-vf", "thumbnail", "-frames:v", "1", str(out)])
    except ConvertError:
        _ff(["-i", str(src), "-frames:v", "1", str(out)])


@rule("gif apng", VIDEO_OUT, need=("ffmpeg",), cost=5, label="gif to video",
      chainable=False)
def gif_to_video(src, out, dst):
    to_video(src, out, dst)
