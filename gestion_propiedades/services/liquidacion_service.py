from decimal import Decimal
from django.db.models import Q, Sum
from ..models import (
    ReciboPago,
    MantenimientoUnidad,
    GastoGeneralPropietario,
    LiquidacionPropietario,
)


def desglosar_recibo_propietario(recibo):
    """
    Retorna un diccionario con los componentes de un ReciboPago desde la óptica
    de la liquidación al propietario y los ingresos propios de la agencia.
    Si el recibo no está ACTIVO, todo retorna 0.00.
    """
    cero = Decimal('0.00')
    if not recibo or recibo.estado != 'ACTIVO':
        return {
            'renta': cero,
            'servicios': cero,
            'mora_propietario': cero,
            'mora_agencia': cero,
            'total_propietario': cero,
            'total_cobrado': cero,
        }

    m_pagado = Decimal(str(recibo.monto_pagado or '0.00'))
    m_renta = Decimal(str(recibo.monto_a_renta or '0.00'))
    m_serv = Decimal(str(recibo.monto_a_servicios or '0.00'))
    m_mora = Decimal(str(recibo.monto_a_mora or '0.00'))

    # Compatibilidad con recibos históricos anteriores a la imputación por rubros
    if m_renta == cero and m_serv == cero and m_mora == cero and m_pagado > cero:
        m_renta = m_pagado

    mora_prop = recibo.mora_para_propietario
    mora_ag = recibo.mora_para_agencia
    total_prop = m_renta + m_serv + mora_prop

    return {
        'renta': m_renta,
        'servicios': m_serv,
        'mora_propietario': mora_prop,
        'mora_agencia': mora_ag,
        'total_propietario': total_prop,
        'total_cobrado': m_pagado,
    }


def calcular_renta_cobrada_itbis(propietario_id, mes, anio):
    """
    Calcula la base de alquiler puro cobrado (excluyendo moras y servicios)
    para el cálculo sugerido de ITBIS 18% de un propietario en un período.
    """
    recibos = ReciboPago.objects.filter(
        factura__contrato__propiedad__propietario_inmueble_id=propietario_id,
        fecha_pago__month=mes,
        fecha_pago__year=anio,
        estado='ACTIVO',
    )
    total_renta = Decimal('0.00')
    for r in recibos:
        total_renta += desglosar_recibo_propietario(r)['renta']
    return total_renta


def calcular_resumen_liquidacion_periodo(propiedades, mes, anio, propietario=None):
    """
    Calcula todos los montos de liquidación para un conjunto de propiedades en mes/anio:
    - Excluye recibos anulados (solo estado='ACTIVO').
    - Excluye mora perteneciente a la agencia de rentas cobradas, neto, comisión e ITBIS.
    - Si la mora es compartida, incluye únicamente la porción del propietario.
    """
    cero = Decimal('0.00')
    propiedades_list = list(propiedades.select_related('portafolio')) if hasattr(propiedades, 'select_related') else list(propiedades)
    if not propiedades_list:
        return {
            'recibos_activos': [],
            'recibos_propietario': [],
            'total_renta_cobrada': cero,
            'total_servicios_cobrados': cero,
            'total_mora_propietario': cero,
            'total_mora_agencia': cero,
            'total_ingresos_propietario': cero,
            'monto_comision': cero,
            'gastos_directos_list': [],
            'total_gastos_propiedades': cero,
            'gastos_generales_list': [],
            'total_gastos_generales': cero,
            'total_deducciones': cero,
            'neto_a_liquidar_mes': cero,
            'mostrar_mora_agencia': False,
        }

    prop_ids = [p.id for p in propiedades_list]
    recibos_qs = ReciboPago.objects.filter(
        factura__contrato__propiedad_id__in=prop_ids,
        fecha_pago__month=mes,
        fecha_pago__year=anio,
        estado='ACTIVO',
    ).select_related(
        'factura',
        'factura__contrato',
        'factura__contrato__propiedad',
        'factura__contrato__propiedad__portafolio',
        'factura__contrato__inquilino',
    ).order_by('fecha_pago', 'id')

    total_renta_cobrada = cero
    total_servicios_cobrados = cero
    total_mora_propietario = cero
    total_mora_agencia = cero
    recibos_activos = []
    recibos_propietario = []

    for r in recibos_qs:
        d = desglosar_recibo_propietario(r)
        r.monto_propietario_liquidacion = d['total_propietario']
        r.renta_liquidacion = d['renta']
        r.servicios_liquidacion = d['servicios']
        r.mora_propietario_liquidacion = d['mora_propietario']
        r.mora_agencia_liquidacion = d['mora_agencia']

        total_renta_cobrada += d['renta']
        total_servicios_cobrados += d['servicios']
        total_mora_propietario += d['mora_propietario']
        total_mora_agencia += d['mora_agencia']

        recibos_activos.append(r)
        if d['total_propietario'] > cero:
            recibos_propietario.append(r)

    total_ingresos_propietario = total_renta_cobrada + total_servicios_cobrados + total_mora_propietario

    monto_comision = cero
    if propietario:
        if propietario.tipo_comision == 'PORCENTAJE':
            factor = (propietario.porcentaje_comision or cero) / Decimal('100.0')
            monto_comision = round(total_renta_cobrada * factor, 2)
        else:
            monto_comision = (propietario.monto_comision_fijo or cero) * len(propiedades_list)

    gastos_directos_list = list(
        MantenimientoUnidad.objects.filter(
            propiedad_id__in=prop_ids,
            fecha_reporte__month=mes,
            fecha_reporte__year=anio,
        ).select_related('propiedad')
    )
    total_gastos_propiedades = sum((Decimal(str(m.costo or '0.00')) for m in gastos_directos_list), cero)

    if propietario:
        gastos_gen_qs = GastoGeneralPropietario.objects.filter(
            Q(propietario_inmueble=propietario) | Q(propiedad_id__in=prop_ids),
            fecha__month=mes,
            fecha__year=anio,
        )
    else:
        gastos_gen_qs = GastoGeneralPropietario.objects.filter(
            propiedad_id__in=prop_ids,
            fecha__month=mes,
            fecha__year=anio,
        )
    gastos_generales_list = list(gastos_gen_qs)
    total_gastos_generales = sum((Decimal(str(g.monto or '0.00')) for g in gastos_generales_list), cero)

    total_deducciones = monto_comision + total_gastos_propiedades + total_gastos_generales
    neto_a_liquidar_mes = max(cero, total_ingresos_propietario - total_deducciones)

    if propietario and propietario.portafolio_id:
        habilitado_mostrar = bool(propietario.portafolio.mostrar_mora_agencia_en_liquidacion)
    else:
        habilitado_mostrar = any(bool(p.portafolio.mostrar_mora_agencia_en_liquidacion) for p in propiedades_list if p.portafolio_id)

    mostrar_mora_agencia = habilitado_mostrar and (total_mora_agencia > cero)

    return {
        'recibos_activos': recibos_activos,
        'recibos_propietario': recibos_propietario,
        'total_renta_cobrada': total_renta_cobrada,
        'total_servicios_cobrados': total_servicios_cobrados,
        'total_mora_propietario': total_mora_propietario,
        'total_mora_agencia': total_mora_agencia,
        'total_ingresos_propietario': total_ingresos_propietario,
        'monto_comision': monto_comision,
        'gastos_directos_list': gastos_directos_list,
        'total_gastos_propiedades': total_gastos_propiedades,
        'gastos_generales_list': gastos_generales_list,
        'total_gastos_generales': total_gastos_generales,
        'total_deducciones': total_deducciones,
        'neto_a_liquidar_mes': neto_a_liquidar_mes,
        'mostrar_mora_agencia': mostrar_mora_agencia,
    }


def evaluar_diferencia_borrador(liquidacion_borrador, resumen):
    """
    Si existe una liquidación en borrador (PENDIENTE), calcula las diferencias
    entre sus montos guardados y el resumen recalculado actual.
    """
    if not liquidacion_borrador or liquidacion_borrador.estado != 'PENDIENTE':
        return None
    diff_ingresos = resumen['total_ingresos_propietario'] - Decimal(str(liquidacion_borrador.monto_rentas_cobradas or '0.00'))
    diff_comision = resumen['monto_comision'] - Decimal(str(liquidacion_borrador.monto_comision or '0.00'))
    diff_neto = resumen['neto_a_liquidar_mes'] - Decimal(str(liquidacion_borrador.monto_neto_pagado or '0.00'))
    cero = Decimal('0.00')
    if diff_ingresos == cero and diff_comision == cero and diff_neto == cero:
        return None
    return {
        'ingresos_anterior': liquidacion_borrador.monto_rentas_cobradas,
        'ingresos_nuevo': resumen['total_ingresos_propietario'],
        'diff_ingresos': diff_ingresos,
        'comision_anterior': liquidacion_borrador.monto_comision,
        'comision_nuevo': resumen['monto_comision'],
        'diff_comision': diff_comision,
        'neto_anterior': liquidacion_borrador.monto_neto_pagado,
        'neto_nuevo': resumen['neto_a_liquidar_mes'],
        'diff_neto': diff_neto,
    }
