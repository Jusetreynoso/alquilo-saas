import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'alquilo_core.settings')
django.setup()

from django.core.management import call_command
from django.contrib.auth.models import User

# 1. Ejecutar las migraciones obligatoriamente en la Nube
call_command('migrate', interactive=False)

# 2. Crear el superusuario MAESTRO si la base de datos está vacía
if not User.objects.filter(is_superuser=True).exists():
    admin = User.objects.create_superuser(
        username=os.environ.get('MASTER_USER', 'jreynoso_admin'),
        email=os.environ.get('MASTER_EMAIL', 'admin@alquilo.com'),
        password=os.environ.get('MASTER_PASS', 'AlquiloMaster2026!')
    )
    print("Migraciones listas y Superusuario maestro inyectado con éxito.")
