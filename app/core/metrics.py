"""Métricas de negocio y seguridad para Prometheus/Grafana (A09)."""
from prometheus_client import Counter

LOGINS_OK = Counter("familias_logins_total", "Inicios de sesión exitosos", ["metodo"])
LOGINS_FALLIDOS = Counter("familias_logins_fallidos_total", "Inicios de sesión fallidos", ["motivo"])
REGISTROS = Counter("familias_registros_total", "Cuentas creadas", ["metodo"])
INSCRIPCIONES = Counter("familias_inscripciones_total", "Inscripciones a actividades", ["resultado"])
ACCESOS_DENEGADOS = Counter("familias_accesos_denegados_total", "Respuestas 401/403/404 por autorización", ["codigo"])
UPLOADS_RECHAZADOS = Counter("familias_uploads_rechazados_total", "Archivos rechazados por validación")
