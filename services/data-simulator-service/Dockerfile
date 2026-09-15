FROM python:3.12-slim
WORKDIR /app
COPY services/data-simulator-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/data-simulator-service/app ./app
COPY nextfarm_device ./nextfarm_device
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
