#!/bin/bash
# Sobe backend (8184) e frontend (5184) da Geo Showcase.
#
# É o launcher que o PoV Portfolio executa: `bash start.sh` com o cwd no
# repositório, numa sessão nova; o portal espera a URL do frontend e o
# /health/live do backend responderem. Ao encerrar, manda SIGTERM para o grupo
# do launcher e depois para quem escuta nas portas com cwd dentro deste repo.
#
# Daí três exigências:
#   1. ficar em primeiro plano, para o grupo de processos segurar os filhos;
#   2. derrubar a árvore inteira no SIGTERM: `npm run preview` gera um neto
#      (vite) que continua escutando se só o npm morrer;
#   3. tolerar uma porta que ainda está fechando da ativação anterior.
#
# Portas: 8184/5184 (PORTS.md). POV_BACKEND_PORT/POV_FRONTEND_PORT (o portal os
# exporta a partir do povs.json) trocam as portas só para a instância de teste
# do portal; fora dele, use os padrões.
set -u

BASE="$(cd "$(dirname "$0")" && pwd)"
BACKEND_PORT="${POV_BACKEND_PORT:-8184}"
FRONTEND_PORT="${POV_FRONTEND_PORT:-5184}"
BACKEND_LOG="${TMPDIR:-/tmp}/geo-showcase-backend-$BACKEND_PORT.log"
FRONTEND_LOG="${TMPDIR:-/tmp}/geo-showcase-frontend-$FRONTEND_PORT.log"
PORT_WAIT_SECONDS=10

BACKEND_PID=""
FRONTEND_PID=""

fail() { echo "ERRO: $1" >&2; exit 1; }

# Lista o processo e seus descendentes (npm → vite), de cima para baixo.
tree_pids() {
  local pid="$1"
  [[ -z "$pid" ]] && return 0
  echo "$pid"
  local kid
  for kid in $(pgrep -P "$pid" 2>/dev/null || true); do tree_pids "$kid"; done
}

TREE=()
cleanup() {
  trap - EXIT INT TERM
  # Guarda os PIDs ANTES do TERM: depois dele o vite neto é reparentado ao
  # launchd e pgrep -P já não o acharia na passada do KILL.
  TREE=($(tree_pids "$FRONTEND_PID") $(tree_pids "$BACKEND_PID"))
  [[ ${#TREE[@]} -eq 0 ]] && return 0
  kill -TERM "${TREE[@]}" 2>/dev/null || true
  sleep 1
  kill -KILL "${TREE[@]}" 2>/dev/null || true
}
# Armado antes de subir qualquer coisa. Sinal durante a partida limpa E encerra
# o script: sem o exit, ele seguiria no wait_for_url e subiria o frontend já sem trap.
trap 'cleanup; exit 143' TERM
trap 'cleanup; exit 130' INT
trap cleanup EXIT

wait_for_url() {
  local url="$1" attempts="${2:-40}"
  for ((i = 1; i <= attempts; i++)); do
    curl --fail --silent --max-time 2 "$url" >/dev/null && return 0
    sleep 1
  done
  return 1
}

wait_port_free() {
  local port="$1"
  for ((i = 0; i < PORT_WAIT_SECONDS; i++)); do
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1 || return 0
    sleep 1
  done
  return 1
}

command -v curl >/dev/null || fail "curl não encontrado."
command -v npm >/dev/null || fail "npm não encontrado."
[[ -f "$BASE/backend/.env" ]] || fail "Falta backend/.env. Copie backend/.env.example e preencha MONGO_URI."
[[ -x "$BASE/backend/venv/bin/uvicorn" ]] || fail "Virtualenv do backend ausente. Veja Setup no README."
[[ -d "$BASE/frontend/node_modules" ]] || fail "Dependências do frontend ausentes. Rode npm install em frontend/."

# Porta ocupada não é morta aqui (nunca matar o que não é seu); só espera a
# ativação anterior terminar de fechar.
for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
  wait_port_free "$port" || fail "Porta $port segue ocupada após ${PORT_WAIT_SECONDS}s; o processo existente foi preservado."
done

# Portas trocadas (instância de teste do portal): a origem do frontend muda e o
# proxy do Vite precisa apontar para o backend certo. O ambiente vence o .env.
if [[ "$FRONTEND_PORT" != "5184" ]]; then
  export ALLOWED_ORIGINS="http://localhost:$FRONTEND_PORT,http://127.0.0.1:$FRONTEND_PORT"
fi
export VITE_API_PROXY_TARGET="http://127.0.0.1:$BACKEND_PORT"

echo "Geo Showcase · MongoDB Atlas"
echo "backend (porta $BACKEND_PORT)..."
cd "$BASE/backend"
UVICORN_ARGS=(main:app --host 127.0.0.1 --port "$BACKEND_PORT")
[[ "${POV_DEV:-${DEV:-0}}" == "1" ]] && UVICORN_ARGS+=(--reload)
venv/bin/uvicorn "${UVICORN_ARGS[@]}" > "$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!

if ! wait_for_url "http://127.0.0.1:$BACKEND_PORT/health/live" 40; then
  echo "ERRO: backend não ficou pronto. Últimas linhas do log:" >&2
  tail -n 25 "$BACKEND_LOG" >&2
  exit 1
fi

echo "frontend (porta $FRONTEND_PORT)..."
cd "$BASE/frontend"
if [[ "${POV_DEV:-${DEV:-0}}" == "1" ]]; then
  npm run dev -- --port "$FRONTEND_PORT" --strictPort > "$FRONTEND_LOG" 2>&1 &
else
  # Reconstrói só quando a fonte mudou; o bundle pronto evita um watcher por PoV aberta.
  if [[ ! -d dist ]] || [[ -n "$(find src index.html vite.config.js package-lock.json -newer dist -print -quit 2>/dev/null)" ]]; then
    npm run build > "$FRONTEND_LOG" 2>&1 || { echo "ERRO: build do frontend falhou" >&2; tail -n 20 "$FRONTEND_LOG" >&2; exit 1; }
  fi
  npm run preview -- --port "$FRONTEND_PORT" --strictPort >> "$FRONTEND_LOG" 2>&1 &
fi
FRONTEND_PID=$!

if ! wait_for_url "http://127.0.0.1:$FRONTEND_PORT/" 40; then
  echo "ERRO: frontend não ficou pronto." >&2
  tail -n 25 "$FRONTEND_LOG" >&2
  exit 1
fi

echo
echo "pronto"
echo "   UI         http://127.0.0.1:$FRONTEND_PORT"
echo "   API        http://127.0.0.1:$BACKEND_PORT/docs"
echo "   preflight  http://127.0.0.1:$BACKEND_PORT/preflight"

# Primeiro plano de propósito: o portal segura este processo como o grupo da PoV.
wait
