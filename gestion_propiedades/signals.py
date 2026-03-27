import threading
from django.db.models.signals import post_save, post_delete
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
    if usuario and usuario.is_authenticated:
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
