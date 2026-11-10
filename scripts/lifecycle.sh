#!/usr/bin/env bash
# voice-score install lifecycle: setup | update | remove | status.
# Run by ownbox with the checkout as working directory (ownbox does not export
# OWNBOX_TOOL_DIR to lifecycle commands, so the checkout is derived from this script).
# Stateless service: there is no user data to migrate. The only optional data is
# the RMVPE model (362 MB), kept off root in /mnt/windows/voice-score-data/models.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT=voice-score.service
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
PORT="${VOICE_SCORE_PORT:-3311}"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

log() { printf 'voice-score: %s\n' "$*" >&2; }

ask() {  # ask "question" default(y/n) -> 0 for yes
    local def="$2" reply
    if [[ ! -t 0 ]]; then [[ "$def" == y ]]; return; fi
    read -r -p "$1 [$( [[ $def == y ]] && echo Y/n || echo y/N )] " reply || reply=""
    reply="${reply:-$def}"
    [[ "$reply" =~ ^[Yy] ]]
}

build_venv() {
    cd "$ROOT"
    # Root disk is tight on archserver; keep uv's cache on the offload volume when present.
    if mountpoint -q /mnt/offload 2>/dev/null && [[ -w /mnt/offload/uv-cache ]]; then
        export UV_CACHE_DIR=/mnt/offload/uv-cache
    fi
    if command -v uv >/dev/null; then
        uv sync --frozen --no-dev --quiet
    else
        log "uv not found; falling back to python -m venv + pip"
        python3 -m venv .venv
        .venv/bin/python -m pip install --quiet -e .
    fi
    .venv/bin/voice-score --version >&2
}

write_unit() {
    mkdir -p "$UNIT_DIR"
    cat > "$UNIT_DIR/$UNIT" <<UNITEOF
[Unit]
Description=voice-score singing analysis API (127.0.0.1:$PORT)
After=network.target

[Service]
Type=simple
WorkingDirectory=$ROOT
Environment=VOICE_SCORE_HOST=127.0.0.1
Environment=VOICE_SCORE_PORT=$PORT
ExecStart=$ROOT/.venv/bin/voice-score serve
Restart=on-failure
RestartSec=3
# onnxruntime thread pool; leave cores for the trainer and other agents
CPUQuota=400%
MemoryMax=2G

[Install]
WantedBy=default.target
UNITEOF
    systemctl --user daemon-reload
}

wait_health() {
    for _ in $(seq 1 40); do
        if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
            log "healthy on 127.0.0.1:$PORT"; return 0
        fi
        sleep 0.5
    done
    log "service did not become healthy; journalctl --user -u $UNIT -n 50"
    return 1
}

fetch_models() {
    if [[ -f "$ROOT/scripts/fetch-models.sh" ]] && ask "Download the optional RMVPE model (362 MB, to /mnt/windows)?" n; then
        bash "$ROOT/scripts/fetch-models.sh"
    else
        log "skipped optional RMVPE model download (run scripts/fetch-models.sh later if wanted)"
    fi
}

case "${1:-}" in
    setup)
        build_venv
        write_unit
        systemctl --user enable "$UNIT" >/dev/null 2>&1
        systemctl --user restart "$UNIT"
        wait_health
        fetch_models
        ;;
    update)
        build_venv
        write_unit
        systemctl --user enable "$UNIT" >/dev/null 2>&1
        systemctl --user restart "$UNIT"
        wait_health
        ;;
    remove)
        systemctl --user disable --now "$UNIT" >/dev/null 2>&1 || true
        rm -f "$UNIT_DIR/$UNIT"
        systemctl --user daemon-reload || true
        if [[ -d /mnt/windows/voice-score-data/models ]]; then
            if ask "Delete downloaded models in /mnt/windows/voice-score-data/models?" n; then
                rm -rf /mnt/windows/voice-score-data/models
            else
                log "kept /mnt/windows/voice-score-data/models"
            fi
        fi
        log "removed service unit"
        ;;
    status)
        systemctl --user --no-pager status "$UNIT" | head -5 || true
        curl -fsS "http://127.0.0.1:$PORT/health" && echo || log "not answering on $PORT"
        ;;
    *)
        echo "usage: $0 setup|update|remove|status" >&2; exit 2 ;;
esac
