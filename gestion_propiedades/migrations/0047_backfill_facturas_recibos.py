from django.db import migrations
from django.db.models import F

def backfill_datos(apps, schema_editor):
    Factura = apps.get_model('gestion_propiedades', 'Factura')
    ReciboPago = apps.get_model('gestion_propiedades', 'ReciboPago')

    Factura.objects.filter(monto_renta=0, monto_servicios=0).update(monto_renta=F('monto_base'))
    ReciboPago.objects.filter(monto_a_renta=0, monto_a_servicios=0, monto_a_mora=0).update(monto_a_renta=F('monto_pagado'))

def revertir_datos(apps, schema_editor):
    pass

class Migration(migrations.Migration):

    dependencies = [
        ('gestion_propiedades', '0046_factura_monto_renta_factura_monto_servicios_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_datos, revertir_datos),
    ]
