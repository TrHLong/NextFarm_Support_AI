FROM python:3.11-slim
WORKDIR /app
COPY services/farm-data-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/farm-data-service/app ./app
COPY nextfarm_device ./nextfarm_device
COPY scripts/import_device_reference.py ./import_device_reference.py
COPY docs/references/Chat-thiet-bi-NextFarm-v0.1.html ./device-reference.html
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
