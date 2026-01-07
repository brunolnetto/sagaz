"""Orders app configuration."""

from django.apps import AppConfig


class OrdersConfig(AppConfig):
    """Django app config that initializes Sagaz on startup."""
    
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'orders'
    
    def ready(self):
        """Initialize Sagaz when Django starts."""
        from django.conf import settings
        from sagaz import SagaConfig, configure
        
        sagaz_settings = getattr(settings, 'SAGAZ', {})
        
        config = SagaConfig(
            metrics=sagaz_settings.get('METRICS', False),
            logging=sagaz_settings.get('LOGGING', False),
        )
        configure(config)
        
        print("✅ Sagaz initialized via Django AppConfig")
