"""Contrato do launcher `start.sh` com o PoV Portfolio (2026-11-13).

O portal roda `bash start.sh` numa sessão nova, espera frontend e
`/health/live`, e encerra com SIGTERM no grupo. O script precisa ficar em
primeiro plano, armar a limpeza antes de subir filhos e honrar as portas que o
portal exporta (instância de teste) mantendo 8184/5184 como padrão.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

START = Path(__file__).resolve().parents[2] / "start.sh"


def _text() -> str:
    return START.read_text(encoding="utf-8")


def test_start_sh_is_valid_bash() -> None:
    subprocess.run(["bash", "-n", str(START)], check=True)


def test_default_ports_match_ports_md() -> None:
    text = _text()
    assert 'BACKEND_PORT="${POV_BACKEND_PORT:-8184}"' in text
    assert 'FRONTEND_PORT="${POV_FRONTEND_PORT:-5184}"' in text


def test_cleanup_armed_before_children_and_foreground_wait() -> None:
    text = _text()
    trap_at = text.index("trap cleanup EXIT INT TERM")
    assert trap_at < text.index("venv/bin/uvicorn")
    assert "kill_tree" in text  # npm → vite: matar só o npm deixaria o vite na porta
    assert text.rstrip().endswith("wait")


def test_preview_uses_launcher_port_and_proxy_target() -> None:
    text = _text()
    assert 'npm run preview -- --port "$FRONTEND_PORT" --strictPort' in text
    assert 'VITE_API_PROXY_TARGET="http://127.0.0.1:$BACKEND_PORT"' in text
    assert "/health/live" in text
