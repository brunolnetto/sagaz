"""
Sagaz Framework Integrations

Provides integration helpers for popular web frameworks:
- FastAPI
- Flask
- Django

Each integration provides:
- Context propagation middleware
- Saga lifecycle management
- Request correlation IDs
- Webhook endpoints for event triggers
"""

from sagaz.integrations._base import (
    SagaContextManager,
    generate_correlation_id,
    get_correlation_id,
)

__all__ = [
    "SagaContextManager",
    "generate_correlation_id",
    "get_correlation_id",
]
