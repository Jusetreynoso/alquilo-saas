import threading
from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from .models import Contrato, Factura, ReciboPago, MantenimientoUnidad, AuditLog


def get_current_user():
    # Import lazily to avoid circular import at module load time
    from .middleware import _thread_local
    return getattr(_thread_local, 'usuario', None)


def _portafolio_de(instance):
    """Intenta extraer el portafolio del objeto para el filtrado multi-tenant."""
    try:
        if hasattr(instance, 'propiedad'):
            return instance.propiedad.portafolio
        if hasattr(instance, 'contrato'):
            return instance.contrato.propiedad.portafolio
        if hasattr(instance, 'factura'):
            return instance.factura.contrato.propiedad.portafolio
    except Exception:
        pass
    return None


def _registrar(accion, modulo, descripcion, portafolio):
    usuario = get_current_user()
    if usuario and usuario.is_authenticated and getattr(usuario, 'pk', None):
        try:
            from django.contrib.auth.models import User
            if not User.objects.filter(pk=usuario.pk).exists():
                return
        except Exception:
            return
        AuditLog.objects.create(
            accion=accion,
            modulo=modulo,
            descripcion=descripcion,
            usuario=usuario,
            portafolio=portafolio,
        )


# ---- Contrato ----
@receiver(post_save, sender=Contrato)
def audit_contrato(sender, instance, created, **kwargs):
    accion = 'CREAR' if created else 'EDITAR'
    desc = f"Contrato #{instance.id} — {instance.propiedad} / {instance.inquilino.nombre}"
    _registrar(accion, 'Contrato', desc, instance.propiedad.portafolio)


@receiver(post_delete, sender=Contrato)
def audit_contrato_delete(sender, instance, **kwargs):
    desc = f"Contrato #{instance.id} — {instance.propiedad} / {instance.inquilino.nombre}"
    _registrar('ELIMINAR', 'Contrato', desc, _portafolio_de(instance) or instance.propiedad.portafolio)


# ---- Factura ----
@receiver(post_save, sender=Factura)
def audit_factura(sender, instance, created, **kwargs):
    accion = 'CREAR' if created else 'EDITAR'
    desc = f"Factura #{instance.id} — {instance.contrato.inquilino.nombre} — Estado: {instance.estado} — ${instance.monto_base}"
    _registrar(accion, 'Factura', desc, _portafolio_de(instance))


@receiver(post_delete, sender=Factura)
def audit_factura_delete(sender, instance, **kwargs):
    desc = f"Factura #{instance.id} eliminada"
    _registrar('ELIMINAR', 'Factura', desc, _portafolio_de(instance))


# ---- ReciboPago ----
@receiver(post_save, sender=ReciboPago)
def audit_recibo(sender, instance, created, **kwargs):
    accion = 'CREAR' if created else 'EDITAR'
    desc = (
        f"Recibo #{instance.id} — "
        f"${instance.monto_pagado} vía {instance.get_metodo_pago_display()} "
        f"para Factura #{instance.factura.id}"
    )
    _registrar(accion, 'ReciboPago', desc, _portafolio_de(instance))


@receiver(post_delete, sender=ReciboPago)
def audit_recibo_delete(sender, instance, **kwargs):
    desc = f"Recibo #{instance.id} eliminado"
    _registrar('ELIMINAR', 'ReciboPago', desc, _portafolio_de(instance))


# ---- MantenimientoUnidad ----
@receiver(post_save, sender=MantenimientoUnidad)
def audit_mantenimiento(sender, instance, created, **kwargs):
    accion = 'CREAR' if created else 'EDITAR'
    desc = (
        f"Mantenimiento #{instance.id} — "
        f"{instance.get_categoria_display()} en {instance.propiedad} — "
        f"Estado: {instance.get_estado_display()} — Costo: ${instance.costo}"
    )
    _registrar(accion, 'Mantenimiento', desc, instance.propiedad.portafolio)


@receiver(post_delete, sender=MantenimientoUnidad)
def audit_mantenimiento_delete(sender, instance, **kwargs):
    desc = f"Mantenimiento #{instance.id} eliminado de {instance.propiedad}"
    _registrar('ELIMINAR', 'Mantenimiento', desc, _portafolio_de(instance) or instance.propiedad.portafolio)

# =====================================================================
# OPTIMIZACIÓN Y COMPRESIÓN AUTOMÁTICA DE IMÁGENES / ARCHIVOS (Cloudinary & Local)
# Reduce el peso hasta un 90% preservando legibilidad de contratos y comprobantes.
# =====================================================================
from .utils_imagen import optimizar_campo_imagen, optimizar_campos_modelo
from .models import (
    Propiedad,
    ImagenPropiedad,
    Portafolio,
    FacturaSaaS,
    GastoGeneralPropietario,
    ImagenPublicacion,
    SolicitudAlquiler
)


@receiver(pre_save, sender=ReciboPago)
def optimizar_recibo_pago_imagen(sender, instance, **kwargs):
    optimizar_campo_imagen(instance, 'comprobante_imagen')


@receiver(pre_save, sender=Contrato)
def optimizar_contrato_adjuntos(sender, instance, **kwargs):
    optimizar_campos_modelo(instance, [
        'documento_contrato',
        'fotos_entrega',
        'foto_entrega_2',
        'foto_entrega_3',
        'foto_entrega_4',
        'foto_entrega_5'
    ])


@receiver(pre_save, sender=Propiedad)
def optimizar_propiedad_fachada(sender, instance, **kwargs):
    optimizar_campo_imagen(instance, 'imagen_principal')


@receiver(pre_save, sender=ImagenPropiedad)
def optimizar_propiedad_galeria(sender, instance, **kwargs):
    optimizar_campo_imagen(instance, 'imagen')


@receiver(pre_save, sender=Portafolio)
def optimizar_portafolio_logo(sender, instance, **kwargs):
    optimizar_campo_imagen(instance, 'logo_empresa', max_dimension=800, calidad=85)


@receiver(pre_save, sender=FacturaSaaS)
def optimizar_factura_saas_comprobante(sender, instance, **kwargs):
    optimizar_campo_imagen(instance, 'comprobante_pago')


@receiver(pre_save, sender=MantenimientoUnidad)
def optimizar_mantenimiento_factura(sender, instance, **kwargs):
    optimizar_campo_imagen(instance, 'factura_adjunta')


@receiver(pre_save, sender=GastoGeneralPropietario)
def optimizar_gasto_propietario_factura(sender, instance, **kwargs):
    optimizar_campo_imagen(instance, 'factura_adjunta')


@receiver(pre_save, sender=ImagenPublicacion)
def optimizar_marketplace_imagen(sender, instance, **kwargs):
    optimizar_campo_imagen(instance, 'imagen')


@receiver(pre_save, sender=SolicitudAlquiler)
def optimizar_solicitud_adjuntos(sender, instance, **kwargs):
    optimizar_campos_modelo(instance, [
        'adjunto_cedula_solicitante',
        'adjunto_ingresos_solicitante',
        'adjunto_cedula_fiador',
        'adjunto_ingresos_fiador'
    ])
