FROM python:3.12-slim
WORKDIR /app
COPY services/truth-guard-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/truth-guard-service/app ./app
COPY services/truth-guard-service/tests ./tests
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
