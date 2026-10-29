#!/usr/bin/env bash
# Container entrypoint. Usage: entrypoint.sh web|worker|beat|migrate|shell
#   migrate  migrate → roles → admin → reference data → (DEMO_DATA=1 seed once | reseed rebuild)
#   web      migrate step (unless MIGRATE_ON_START=0), then gunicorn
# Every step is idempotent. On NHF's servers set MIGRATE_ON_START=0 and run `migrate` as a release job.
set -euo pipefail
PORT="${PORT:-8000}"
WEB_CONCURRENCY="${WEB_CONCURRENCY:-$(( $(nproc) * 2 + 1 ))}"
if [ "$WEB_CONCURRENCY" -gt 8 ]; then WEB_CONCURRENCY=8; fi

schema_step() {
  echo "[entrypoint] migrate + bootstrap (DEMO_DATA=${DEMO_DATA:-0})"
  python manage.py migrate --noinput
  python manage.py bootstrap_roles
  python manage.py bootstrap_admin
  python manage.py bootstrap_reference
  case "${DEMO_DATA:-0}" in
    1)      python manage.py seed_demo_data --force --if-missing ;;
    reseed) python manage.py seed_demo_data --force ;;
  esac
  echo "[entrypoint] schema step done"
}

case "${1:-web}" in
  web)
    if [ "${MIGRATE_ON_START:-1}" = "1" ]; then schema_step; fi
    exec gunicorn config.wsgi:application --bind "0.0.0.0:${PORT}" --workers "${WEB_CONCURRENCY}" --threads "${GUNICORN_THREADS:-4}" \
      --worker-class gthread --timeout 60 --graceful-timeout 30 --keep-alive 5 --max-requests 2000 --max-requests-jitter 200 \
      --access-logfile - --error-logfile - --forwarded-allow-ips="*" ;;
  worker) exec celery -A config worker --loglevel=INFO --concurrency "${CELERY_CONCURRENCY:-4}" -Q celery,identity,notify ;;
  beat)   exec celery -A config beat --loglevel=INFO ;;
  migrate) schema_step ;;
  shell)  exec python manage.py shell ;;
  *)      exec "$@" ;;
esac
