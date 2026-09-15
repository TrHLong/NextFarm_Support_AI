"""Device scoped v11 entry point. V10 evidence is retained for audit only."""
from nextfarm_device.runtime import ingestion_app
app = ingestion_app()
