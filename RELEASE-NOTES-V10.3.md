# NextFarm AI Support v10.3
- Thêm dataset simulation 30 ngày / 12 site, seed 20260928.
- Train 5 capability đúng mục tiêu sản phẩm; tất cả gắn scope SYNTHETIC_SIMULATION_ONLY.
- Artifact .joblib + .pkl, report DOCX, chart và prediction CSV.
- FastAPI serving + Docker, online/batch inference, shadow mặc định, A/B 10% deterministic.
- Monitoring inference log và retraining entrypoint tách simulation/production.
- Không thay đổi nguyên tắc v10.2: production training phải qua Data Readiness Gate và không dùng synthetic.
