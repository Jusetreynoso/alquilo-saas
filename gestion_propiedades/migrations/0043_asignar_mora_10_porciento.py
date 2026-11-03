from decimal import Decimal
from django.db import migrations
from django.db.models import Q


def asignar_mora_10_porciento(apps, schema_editor):
    Contrato = apps.get_model('gestion_propiedades', 'Contrato')

    # Buscar todos los contratos de Basora & Arriaga o creados en la carga masiva
    contratos_a_actualizar = Contrato.objects.filter(
        Q(propiedad__portafolio__propietario__username__iexact='lbasora@basoraarriaga.com') |
        Q(propiedad__portafolio__propietario__email__iexact='lbasora@basoraarriaga.com') |
        Q(propiedad__portafolio__nombre__icontains='Basora')
    )

    actualizados = contratos_a_actualizar.update(porcentaje_mora=Decimal('10.00'))
    print(f"\n[Migración 0043] Contratos de Basora & Arriaga actualizados a 10% de mora: {actualizados}")


def revertir_mora(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('gestion_propiedades', '0042_inquilino_cedula_fiador_inquilino_direccion_and_more'),
    ]

    operations = [
        migrations.RunPython(asignar_mora_10_porciento, reverse_code=revertir_mora),
    ]
