FROM python:3.11-slim
WORKDIR /app
COPY services/knowledge-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/knowledge-service/app ./app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
