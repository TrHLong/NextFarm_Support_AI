FROM python:3.12-slim
WORKDIR /app
COPY services/ai-model-serving-service/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY services/ai-model-serving-service/app /app/app
COPY model-artifacts/simulation-v103/latest/models /app/models
ENV NEXTFARM_MODEL_DIR=/app/models NEXTFARM_AI_MODE=shadow NEXTFARM_INFERENCE_LOG_DIR=/app/logs
EXPOSE 8080
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8080"]
