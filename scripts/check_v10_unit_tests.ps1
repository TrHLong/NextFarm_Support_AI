$ErrorActionPreference='Stop'
docker compose exec -T ai-analytics-service python -m pytest tests_device -q
exit $LASTEXITCODE
