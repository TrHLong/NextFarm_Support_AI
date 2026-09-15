"""Device scoped v11 entry point. V10 evidence is retained for audit only."""
from nextfarm_device.api import gateway_app
app = gateway_app()
