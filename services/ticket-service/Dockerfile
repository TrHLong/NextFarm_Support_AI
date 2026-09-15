FROM python:3.11-slim
WORKDIR /app
COPY services/ticket-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/ticket-service/app ./app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
