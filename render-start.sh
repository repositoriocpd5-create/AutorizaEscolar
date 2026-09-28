#!/usr/bin/env bash
# Inicialização no Render: aplica migrations, popula a demonstração (se DEMO_MODE=true)
# e sobe o servidor WSGI.
set -euo pipefail

flask --app wsgi db upgrade

if [ "${DEMO_MODE:-false}" = "true" ]; then
  # Não faz nada se o banco já tiver dados.
  flask --app wsgi seed-demo || echo "seed-demo ignorado"
fi

exec gunicorn wsgi:app \
  --workers "${WEB_CONCURRENCY:-2}" \
  --threads 4 \
  --timeout 60 \
  --bind "0.0.0.0:${PORT:-10000}" \
  --access-logfile -
