import decimal
from datetime import timedelta
from django.utils import timezone


def calcular_fecha_vencimiento_dias_habiles(fecha_inicio, dias_habiles=15):
    """
    Calcula la fecha de vencimiento sumando únicamente días laborables/hábiles (Lunes a Viernes).
    Excluye Sábados y Domingos.
    """
    fecha = fecha_inicio
    dias_agregados = 0
    while dias_agregados < dias_habiles:
        fecha += timedelta(days=1)
        # weekday(): 0 es Lunes, 4 es Viernes, 5 es Sábado, 6 es Domingo
        if fecha.weekday() < 5:
            dias_agregados += 1
    return fecha


def contar_dias_habiles_entre(fecha_desde, fecha_hasta):
    """
    Cuenta cuántos días hábiles hay entre dos fechas (excluyendo el día de inicio, incluyendo el fin).
    Si fecha_hasta <= fecha_desde, retorna 0.
    """
    if fecha_hasta <= fecha_desde:
        return 0
    
    actual = fecha_desde
    dias = 0
    while actual < fecha_hasta:
        actual += timedelta(days=1)
        if actual.weekday() < 5:
            dias += 1
    return dias


def calcular_metricas_facturacion_saas(suscripcion, cant_propiedades=None):
    """
    Calcula el desglose financiero del cobro mensual SaaS según el plan del cliente.
    Maneja tarifas escalonadas (Tiered Pricing):
    - Tarifa base con N propiedades incluidas.
    - Costo por propiedad excedente.
    - Usuarios incluidos (Admin + Asistente) y costo por usuario extra.
    """
    from .models import Propiedad, AccesoPortafolio

    cliente = getattr(suscripcion, 'usuario', None)
    plan = getattr(suscripcion, 'plan_saas', None)

    if cant_propiedades is None:
        if cliente and cliente.pk:
            cant_propiedades = Propiedad.objects.filter(
                portafolio__propietario=cliente,
                is_deleted=False
            ).count()
        else:
            cant_propiedades = 0

    if cliente and cliente.pk:
        cant_asistentes = AccesoPortafolio.objects.filter(portafolio__propietario=cliente).count()
    else:
        cant_asistentes = 0
    usuarios_activos = 1 + cant_asistentes

    if plan:
        monto_base = plan.precio_mensual
        limite_props = plan.limite_propiedades
        precio_unidad_extra = getattr(plan, 'precio_unidad_extra', decimal.Decimal('1.00'))
        usuarios_incluidos = getattr(plan, 'usuarios_incluidos', 2)
        precio_usuario_extra = getattr(plan, 'precio_usuario_extra', decimal.Decimal('1.00'))
        dias_gracia = getattr(plan, 'dias_gracia_habiles', 15)
    else:
        # Fallback sin plan específico: $1 por unidad plana
        monto_base = decimal.Decimal('0.00')
        limite_props = 0
        precio_unidad_extra = decimal.Decimal('1.00')
        usuarios_incluidos = 2
        precio_usuario_extra = decimal.Decimal('1.00')
        dias_gracia = 5

    # Cálculo propiedades excedentes
    if limite_props > 0:
        propiedades_incluidas = min(cant_propiedades, limite_props)
        propiedades_extra = max(0, cant_propiedades - limite_props)
    else:
        propiedades_incluidas = 0
        propiedades_extra = cant_propiedades

    costo_propiedades_extra = decimal.Decimal(str(propiedades_extra)) * precio_unidad_extra

    # Cálculo usuarios excedentes
    asistentes_extra_suscripcion = getattr(suscripcion, 'asistentes_gratuitos_extra', 0)
    max_usuarios_gratis = usuarios_incluidos + asistentes_extra_suscripcion
    usuarios_extra = max(0, usuarios_activos - max_usuarios_gratis)
    costo_usuarios_extra = decimal.Decimal(str(usuarios_extra)) * precio_usuario_extra

    monto_total = monto_base + costo_propiedades_extra + costo_usuarios_extra

    return {
        'plan_nombre': plan.nombre if plan else 'Estándar',
        'monto_base': monto_base,
        'propiedades_total': cant_propiedades,
        'propiedades_incluidas': propiedades_incluidas,
        'propiedades_extra': propiedades_extra,
        'costo_propiedades_extra': costo_propiedades_extra,
        'usuarios_activos': usuarios_activos,
        'usuarios_incluidos': max_usuarios_gratis,
        'usuarios_extra': usuarios_extra,
        'costo_usuarios_extra': costo_usuarios_extra,
        'monto_total': monto_total,
        'dias_gracia_habiles': dias_gracia,
    }
