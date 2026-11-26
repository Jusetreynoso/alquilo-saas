import decimal
import uuid
import threading
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from ..models import Factura, ReciboPago, Contrato, AuditLog

_lock_pagos = threading.Lock()


class ErrorValidacionPago(Exception):
    def __init__(self, mensaje, codigo='ERROR_GENERAL', saldo_pendiente=decimal.Decimal('0.00'), excedente=decimal.Decimal('0.00')):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.codigo = codigo
        self.saldo_pendiente = saldo_pendiente
        self.excedente = excedente


def verificar_posible_duplicado(contrato, monto, referencia=None, ventana_horas=48):
    """
    Detección suave (no bloqueante) de pagos repetidos:
    Busca si en las últimas `ventana_horas` existe un pago activo en el mismo contrato
    con el mismo monto y la misma referencia de transacción (o sin referencia si coincide el monto).
    """
    if not contrato or not monto:
        return None

    try:
        monto_decimal = decimal.Decimal(str(monto))
    except Exception:
        return None

    limite_tiempo = timezone.now() - timedelta(hours=ventana_horas)
    qs = ReciboPago.objects.filter(
        factura__contrato=contrato,
        monto_pagado=monto_decimal,
        estado='ACTIVO',
        registrado_en__gte=limite_tiempo
    ).select_related('factura')

    if referencia and referencia.strip():
        qs_ref = qs.filter(referencia_transaccion__iexact=referencia.strip())
        if qs_ref.exists():
            return qs_ref.first()

    return qs.first() if qs.exists() else None


def registrar_pago_factura(
    factura_id,
    monto,
    metodo_pago='TRANSFERENCIA',
    referencia='',
    fecha_pago=None,
    comprobante=None,
    usuario=None,
    idempotency_token=None,
    permitir_excedente_a_favor=False
):
    """
    Servicio centralizado y atómico para registrar cobros contra una factura.
    Aplica bloqueo de fila (select_for_update) y validaciones estrictas de negocio.
    """
    # 1. Normalización de monto
    try:
        monto_val = decimal.Decimal(str(monto).replace(',', '').strip())
    except Exception:
        raise ErrorValidacionPago("El monto indicado no es un número válido.", codigo='MONTO_INVALIDO')

    if monto_val <= decimal.Decimal('0.00'):
        raise ErrorValidacionPago("El monto recibido debe ser mayor a cero.", codigo='MONTO_INVALIDO')

    if not fecha_pago:
        fecha_pago = timezone.now().date()

    token_val = None
    if idempotency_token:
        try:
            token_val = uuid.UUID(str(idempotency_token))
        except (ValueError, AttributeError):
            token_val = None

    portafolio_para_audit = None
    try:
        factura_temp = Factura.objects.select_related('contrato__propiedad__portafolio').get(id=factura_id)
        if factura_temp.contrato and factura_temp.contrato.propiedad:
            portafolio_para_audit = factura_temp.contrato.propiedad.portafolio
    except Exception:
        pass

    with _lock_pagos:
        try:
            with transaction.atomic():
                # Verificación temprana de idempotencia
                if token_val:
                    recibo_existente = ReciboPago.objects.filter(idempotency_token=token_val).select_related('factura').first()
                    if recibo_existente:
                        return {
                            'recibo': recibo_existente,
                            'factura': recibo_existente.factura,
                            'es_duplicado_idempotente': True,
                            'excedente_a_favor': decimal.Decimal('0.00'),
                        }

                # 2. Bloqueo de factura en la base de datos
                try:
                    factura = Factura.objects.select_for_update().select_related('contrato__propiedad__portafolio').get(id=factura_id)
                except Factura.DoesNotExist:
                    raise ErrorValidacionPago("La factura indicada no existe.", codigo='FACTURA_NO_EXISTE')

                portafolio = None
                try:
                    portafolio = factura.contrato.propiedad.portafolio
                    portafolio_para_audit = portafolio
                except Exception:
                    pass

                # 3. Validar estado de la factura tras bloqueo
                saldo_actual = factura.saldo_pendiente

                if factura.estado == 'ANULADA':
                    raise ErrorValidacionPago(f"Intento de pago de RD$ {monto_val:,.2f} a Factura #{factura.id} que está ANULADA.", codigo='FACTURA_ANULADA')

                if saldo_actual <= decimal.Decimal('0.00') or factura.estado == 'PAGADA':
                    motivo = f"Intento de pago de RD$ {monto_val:,.2f} a Factura #{factura.id} con saldo 0 (PAGADA)."
                    raise ErrorValidacionPago(
                        "Esta factura ya está pagada por completo. Si el inquilino quiere adelantar dinero, regístralo como pago anticipado.",
                        codigo='FACTURA_YA_PAGADA',
                        saldo_pendiente=decimal.Decimal('0.00')
                    )

                # 4. Validar monto vs saldo pendiente
                excedente_a_favor = decimal.Decimal('0.00')
                monto_para_factura = monto_val

                if monto_val > saldo_actual:
                    diferencia = monto_val - saldo_actual
                    if not permitir_excedente_a_favor:
                        raise ErrorValidacionPago(
                            f"El monto recibido (RD$ {monto_val:,.2f}) supera el saldo pendiente de esta factura (RD$ {saldo_actual:,.2f}).",
                            codigo='EXCEDE_SALDO',
                            saldo_pendiente=saldo_actual,
                            excedente=diferencia
                        )
                    else:
                        monto_para_factura = saldo_actual
                        excedente_a_favor = diferencia

                # 5. Crear el Recibo de Pago (su save() imputa 1. Mora, 2. Servicios, 3. Alquiler)
                recibo = None
                try:
                    recibo = ReciboPago.objects.create(
                        factura=factura,
                        fecha_pago=fecha_pago,
                        monto_pagado=monto_para_factura,
                        metodo_pago=metodo_pago,
                        referencia_transaccion=referencia,
                        comprobante_imagen=comprobante,
                        registrado_por=usuario,
                        idempotency_token=token_val,
                        estado='ACTIVO'
                    )
                except Exception as e:
                    # Fallback tolerante si falla exclusivamente la subida del comprobante
                    if comprobante:
                        recibo = ReciboPago.objects.create(
                            factura=factura,
                            fecha_pago=fecha_pago,
                            monto_pagado=monto_para_factura,
                            metodo_pago=metodo_pago,
                            referencia_transaccion=referencia,
                            comprobante_imagen=None,
                            registrado_por=usuario,
                            idempotency_token=token_val,
                            estado='ACTIVO'
                        )
                    else:
                        raise e

                # 6. Actualizar el estado de la factura
                if factura.saldo_pendiente <= decimal.Decimal('0.00'):
                    factura.estado = 'PAGADA'
                elif factura.estado == 'PAGADA':
                    factura.estado = 'PENDIENTE'
                factura.save()

                # 7. Si hubo excedente confirmado, registrarlo en el saldo a favor del contrato
                if excedente_a_favor > decimal.Decimal('0.00') and factura.contrato:
                    contrato = Contrato.objects.select_for_update().get(id=factura.contrato_id)
                    contrato.saldo_a_favor = (contrato.saldo_a_favor or decimal.Decimal('0.00')) + excedente_a_favor
                    contrato.save(update_fields=['saldo_a_favor'])

                    AuditLog.objects.create(
                        accion='CREAR',
                        modulo='Contrato',
                        descripcion=(
                            f"Acreditado excedente de pago de RD$ {excedente_a_favor:,.2f} como saldo a favor "
                            f"en Contrato #{contrato.id} (Factura #{factura.id})."
                        ),
                        usuario=usuario,
                        portafolio=portafolio
                    )

                # 8. Registro de auditoría exitoso
                AuditLog.objects.create(
                    accion='CREAR',
                    modulo='ReciboPago',
                    descripcion=(
                        f"Cobro registrado de RD$ {monto_para_factura:,.2f} en Factura #{factura.id} "
                        f"(Recibo #{recibo.id}, Método: {metodo_pago})."
                    ),
                    usuario=usuario,
                    portafolio=portafolio
                )

                return {
                    'recibo': recibo,
                    'factura': factura,
                    'es_duplicado_idempotente': False,
                    'excedente_a_favor': excedente_a_favor,
                }
        except ErrorValidacionPago as err:
            _auditar_rechazo(usuario, portafolio_para_audit, err.mensaje)
            raise


def registrar_anticipo_contrato(
    contrato_id,
    monto,
    metodo_pago='TRANSFERENCIA',
    referencia='',
    fecha_pago=None,
    comprobante=None,
    usuario=None,
    idempotency_token=None
):
    """
    Registra un pago anticipado legítimo directamente a favor del contrato (saldo_a_favor).
    Nunca se asocia a facturas ya cubiertas.
    """
    try:
        monto_val = decimal.Decimal(str(monto).replace(',', '').strip())
    except Exception:
        raise ErrorValidacionPago("El monto indicado no es un número válido.", codigo='MONTO_INVALIDO')

    if monto_val <= decimal.Decimal('0.00'):
        raise ErrorValidacionPago("El monto recibido debe ser mayor a cero.", codigo='MONTO_INVALIDO')

    with transaction.atomic():
        contrato = Contrato.objects.select_for_update().select_related('propiedad__portafolio').get(id=contrato_id)
        portafolio = contrato.propiedad.portafolio

        contrato.saldo_a_favor = (contrato.saldo_a_favor or decimal.Decimal('0.00')) + monto_val
        contrato.save(update_fields=['saldo_a_favor'])

        AuditLog.objects.create(
            accion='CREAR',
            modulo='Contrato',
            descripcion=(
                f"Pago anticipado de RD$ {monto_val:,.2f} registrado como saldo a favor "
                f"en Contrato #{contrato.id} ({contrato.inquilino.nombre}). Ref: {referencia or 'S/R'}."
            ),
            usuario=usuario,
            portafolio=portafolio
        )

        return {
            'contrato': contrato,
            'monto_anticipo': monto_val,
            'nuevo_saldo_a_favor': contrato.saldo_a_favor,
        }


def aplicar_saldo_a_favor_factura(factura, usuario=None):
    """
    Aplica el saldo a favor disponible en el contrato sobre una factura pendiente de forma atómica.
    Usado automáticamente por el robot diario o al emitir facturas manuales.
    Garantiza que el saldo a favor nunca quede negativo ni se aplique dos veces.
    """
    if not factura or not factura.contrato_id:
        return decimal.Decimal('0.00')

    with transaction.atomic():
        contrato = Contrato.objects.select_for_update().get(id=factura.contrato_id)
        factura_locked = Factura.objects.select_for_update().get(id=factura.id)

        saldo_favor = contrato.saldo_a_favor or decimal.Decimal('0.00')
        saldo_pendiente = factura_locked.saldo_pendiente

        if saldo_favor <= decimal.Decimal('0.00') or saldo_pendiente <= decimal.Decimal('0.00'):
            return decimal.Decimal('0.00')

        monto_a_aplicar = min(saldo_favor, saldo_pendiente)

        contrato.saldo_a_favor = saldo_favor - monto_a_aplicar
        contrato.save(update_fields=['saldo_a_favor'])

        recibo = ReciboPago.objects.create(
            factura=factura_locked,
            fecha_pago=timezone.now().date(),
            monto_pagado=monto_a_aplicar,
            metodo_pago='TRANSFERENCIA',
            referencia_transaccion='Aplicación automática de saldo a favor',
            registrado_por=usuario,
            estado='ACTIVO'
        )

        if factura_locked.saldo_pendiente <= decimal.Decimal('0.00'):
            factura_locked.estado = 'PAGADA'
        factura_locked.save()

        portafolio = None
        try:
            portafolio = contrato.propiedad.portafolio
        except Exception:
            pass

        AuditLog.objects.create(
            accion='CREAR',
            modulo='ReciboPago',
            descripcion=(
                f"Aplicado automáticamente saldo a favor de RD$ {monto_a_aplicar:,.2f} "
                f"en Factura #{factura_locked.id} (Recibo #{recibo.id}). Saldo a favor restante: RD$ {contrato.saldo_a_favor:,.2f}."
            ),
            usuario=usuario,
            portafolio=portafolio
        )

        return monto_a_aplicar


def anular_pago_recibo(recibo_id, usuario, motivo, destino_excedente='SALDO_A_FAVOR'):
    """
    Anulación segura y auditable de un pago duplicado o erróneo.
    Nunca borra el registro de la base de datos: lo marca como ANULADO y recalcula el estado de la factura.
    """
    with transaction.atomic():
        recibo = ReciboPago.objects.select_for_update().select_related('factura__contrato__propiedad__portafolio').get(id=recibo_id)

        if recibo.estado == 'ANULADO':
            raise ErrorValidacionPago("Este recibo ya ha sido anulado previamente.", codigo='RECIBO_YA_ANULADO')

        factura = Factura.objects.select_for_update().get(id=recibo.factura_id)
        portafolio = recibo.factura.contrato.propiedad.portafolio if recibo.factura.contrato else None

        recibo.estado = 'ANULADO'
        recibo.motivo_anulacion = motivo
        recibo.anulado_por = usuario
        recibo.anulado_en = timezone.now()
        recibo.save(update_fields=['estado', 'motivo_anulacion', 'anulado_por', 'anulado_en'])

        # Si el despacho decide que el dinero queda a favor del contrato:
        if destino_excedente == 'SALDO_A_FAVOR' and recibo.factura.contrato:
            contrato = Contrato.objects.select_for_update().get(id=recibo.factura.contrato_id)
            contrato.saldo_a_favor = (contrato.saldo_a_favor or decimal.Decimal('0.00')) + recibo.monto_pagado
            contrato.save(update_fields=['saldo_a_favor'])

        # Recalcular estado de la factura
        if factura.saldo_pendiente > decimal.Decimal('0.00'):
            if factura.fecha_vencimiento and factura.fecha_vencimiento < timezone.now().date():
                factura.estado = 'ATRASADA'
            else:
                factura.estado = 'PENDIENTE'
        else:
            factura.estado = 'PAGADA'
        factura.save(update_fields=['estado'])

        AuditLog.objects.create(
            accion='ANULAR',
            modulo='ReciboPago',
            descripcion=(
                f"Recibo #{recibo.id} de RD$ {recibo.monto_pagado:,.2f} marcado como ANULADO. "
                f"Motivo: {motivo}. Destino excedente: {destino_excedente}."
            ),
            usuario=usuario,
            portafolio=portafolio
        )

        return {
            'recibo': recibo,
            'factura': factura,
            'nuevo_estado_factura': factura.estado,
        }


def _auditar_rechazo(usuario, portafolio, descripcion):
    try:
        AuditLog.objects.create(
            accion='RECHAZAR',
            modulo='ReciboPago',
            descripcion=descripcion,
            usuario=usuario,
            portafolio=portafolio
        )
    except Exception:
        pass
