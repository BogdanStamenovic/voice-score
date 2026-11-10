#!/usr/bin/env bash
# Download the optional RMVPE ONNX model (362 MB, MIT, from the RVC project) off the root disk.
set -euo pipefail
DIR="${VOICE_SCORE_MODELS:-/mnt/windows/voice-score-data/models}"
URL=https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/rmvpe.onnx
SHA=5370e71ac80af8b4b7c793d27efd51fd8bf962de3a7ede0766dac0befa3660fd
if ! mkdir -p "$DIR" 2>/dev/null; then
    DIR="${XDG_DATA_HOME:-$HOME/.local/share}/voice-score/models"
    echo "voice-score: /mnt/windows not available, using $DIR (362 MB on this disk)" >&2
    mkdir -p "$DIR"
fi
if [[ -f "$DIR/rmvpe.onnx" ]] && echo "$SHA  $DIR/rmvpe.onnx" | sha256sum -c --quiet 2>/dev/null; then
    echo "voice-score: rmvpe.onnx already present in $DIR" >&2; exit 0
fi
curl -fL --retry 3 -o "$DIR/rmvpe.onnx.part" "$URL"
echo "$SHA  $DIR/rmvpe.onnx.part" | sha256sum -c --quiet
mv "$DIR/rmvpe.onnx.part" "$DIR/rmvpe.onnx"
echo "voice-score: rmvpe.onnx -> $DIR" >&2
