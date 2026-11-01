from django.db import migrations
import decimal


def crear_plan_b132(apps, schema_editor):
    PlanSaaS = apps.get_model('gestion_propiedades', 'PlanSaaS')
    User = apps.get_model('auth', 'User')
    SuscripcionCliente = apps.get_model('gestion_propiedades', 'SuscripcionCliente')

    plan, _ = PlanSaaS.objects.update_or_create(
        nombre='plan-B132',
        defaults={
            'precio_mensual': decimal.Decimal('70.00'),
            'limite_propiedades': 140,
            'precio_unidad_extra': decimal.Decimal('1.00'),
            'usuarios_incluidos': 2,
            'precio_usuario_extra': decimal.Decimal('1.00'),
            'dias_gracia_habiles': 15,
            'activo': True,
        }
    )

    # Si ya existe el usuario lbasora@basoraarriaga.com, asociar este plan a su suscripción
    usuario = User.objects.filter(email='lbasora@basoraarriaga.com').first()
    if not usuario:
        usuario = User.objects.filter(username='lbasora@basoraarriaga.com').first()
    
    if usuario:
        sub = SuscripcionCliente.objects.filter(usuario=usuario).first()
        if sub:
            sub.plan_saas = plan
            sub.save()


def revertir_plan_b132(apps, schema_editor):
    PlanSaaS = apps.get_model('gestion_propiedades', 'PlanSaaS')
    PlanSaaS.objects.filter(nombre='plan-B132').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('gestion_propiedades', '0039_plansaas_dias_gracia_habiles_and_more'),
    ]

    operations = [
        migrations.RunPython(crear_plan_b132, revertir_plan_b132),
    ]
