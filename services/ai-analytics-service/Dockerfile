FROM python:3.12-slim
ENV MPLBACKEND=Agg
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY services/ai-analytics-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/ai-analytics-service/app ./app
COPY services/ai-analytics-service/tests ./tests
COPY services/ai-analytics-service/offline_smoke_test.py ./offline_smoke_test.py
COPY services/ai-analytics-service/artifact_smoke_test.py ./artifact_smoke_test.py
COPY research-data /research-data
COPY nextfarm_device ./nextfarm_device
COPY tests_device ./tests_device
COPY benchmarks/farmer-v13 ./benchmarks/farmer-v13
COPY scripts/train_device_models.py ./train_device_models.py
COPY scripts/train_problem_b_snapshot.py /app/scripts/train_problem_b_snapshot.py
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
