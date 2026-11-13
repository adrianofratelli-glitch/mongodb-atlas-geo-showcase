"""Contrato do launcher `start.sh` com o PoV Portfolio (2026-11-13).

O portal roda `bash start.sh` numa sessão nova, espera frontend e
`/health/live`, e encerra com SIGTERM no grupo. O script precisa ficar em
primeiro plano, armar a limpeza antes de subir filhos e honrar as portas que o
portal exporta (instância de teste) mantendo 8184/5184 como padrão.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
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
    trap_at = text.index("trap 'cleanup; exit 143' TERM")
    assert trap_at < text.index("venv/bin/uvicorn")
    assert "trap 'cleanup; exit 130' INT" in text
    assert "tree_pids" in text  # npm → vite: PIDs guardados antes do TERM
    assert text.rstrip().endswith("wait")


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def test_sigterm_during_startup_exits_fast_without_children(tmp_path: Path) -> None:
    """SIGTERM no meio do wait_for_url: sai em < 3 s e não deixa o backend vivo.

    Repo falso em tmp_path: o uvicorn é um `sleep` que grava o próprio PID, e o
    `curl` falso sempre falha, então o script fica preso esperando o backend.
    """
    repo = tmp_path / "repo"
    (repo / "backend" / "venv" / "bin").mkdir(parents=True)
    (repo / "frontend" / "node_modules").mkdir(parents=True)
    (repo / "backend" / ".env").write_text("", encoding="utf-8")
    shutil.copy(START, repo / "start.sh")
    pid_file = tmp_path / "backend.pid"
    uvicorn = repo / "backend" / "venv" / "bin" / "uvicorn"
    uvicorn.write_text(f"#!/bin/bash\necho $$ > {pid_file}\nexec sleep 60\n", encoding="utf-8")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name, body in {"curl": "exit 22", "npm": "exit 0"}.items():
        (fake_bin / name).write_text(f"#!/bin/bash\n{body}\n", encoding="utf-8")
    for exe in (uvicorn, fake_bin / "curl", fake_bin / "npm"):
        exe.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        "TMPDIR": str(tmp_path),
        # portas altas e livres: o script só as consulta com lsof
        "POV_BACKEND_PORT": "18994",
        "POV_FRONTEND_PORT": "15994",
    }
    proc = subprocess.Popen(
        ["bash", "start.sh"], cwd=repo, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert pid_file.exists(), "backend falso não subiu"
        backend_pid = int(pid_file.read_text().strip())
        time.sleep(0.3)  # já dentro do wait_for_url
        started = time.monotonic()
        proc.send_signal(signal.SIGTERM)
        code = proc.wait(timeout=5)
        elapsed = time.monotonic() - started
        assert code == 143
        assert elapsed < 3, f"start.sh levou {elapsed:.1f}s para sair"
        assert not _alive(backend_pid), "backend sobreviveu ao SIGTERM"
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)


def test_preview_uses_launcher_port_and_proxy_target() -> None:
    text = _text()
    assert 'npm run preview -- --port "$FRONTEND_PORT" --strictPort' in text
    assert 'VITE_API_PROXY_TARGET="http://127.0.0.1:$BACKEND_PORT"' in text
    assert "/health/live" in text
