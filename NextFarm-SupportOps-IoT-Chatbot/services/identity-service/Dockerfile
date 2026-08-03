FROM python:3.11-slim
WORKDIR /app
COPY services/identity-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/identity-service/app ./app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
