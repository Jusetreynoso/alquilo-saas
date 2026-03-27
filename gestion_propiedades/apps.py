from django.apps import AppConfig


class GestionPropiedadesConfig(AppConfig):
    name = 'gestion_propiedades'

    def ready(self):
        import gestion_propiedades.signals  # noqa: F401
