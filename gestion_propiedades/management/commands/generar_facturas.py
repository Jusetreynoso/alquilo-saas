import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from datetime import timedelta
from gestion_propiedades.models import Contrato, Factura

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Genera facturas automáticas para los contratos en su día de cobro'

    def handle(self, *args, **kwargs):
        hoy = timezone.localtime().date()
        dia_actual = hoy.day
        
        # Diccionario simple
        meses_espanol = {
            1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril', 5: 'Mayo', 6: 'Junio',
            7: 'Julio', 8: 'Agosto', 9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'
        }

        mensaje_inicio = f"Iniciando proceso de facturación para el día {dia_actual} (Fecha: {hoy})..."
        self.stdout.write(mensaje_inicio)
        logger.info(mensaje_inicio)

        contratos = Contrato.objects.filter(activo=True, dia_de_pago=dia_actual)
        facturas_creadas = 0

        for contrato in contratos:
            # Validación segura para evitar crasheos si el contrato tiene datos huérfanos
            nombre_inquilino = "Sin Inquilino"
            if getattr(contrato, 'inquilino', None):
                nombre_inquilino = getattr(contrato.inquilino, 'nombre_completo', f"ID: {contrato.inquilino.id}")

            try:
                msg_eval = f"Evaluando contrato ID {contrato.id} ({nombre_inquilino})..."
                self.stdout.write(msg_eval)
                logger.info(msg_eval)

                with transaction.atomic():
                    # Verificar si no facturamos este mes ya
                    factura_existe = Factura.objects.filter(
                        contrato=contrato,
                        fecha_emision__year=hoy.year,
                        fecha_emision__month=hoy.month
                    ).exists()

                    if not factura_existe:
                        fecha_vence = hoy + timedelta(days=5)
                        nombre_mes = meses_espanol[hoy.month]

                        Factura.objects.create(
                            contrato=contrato,
                            fecha_emision=hoy,
                            fecha_vencimiento=fecha_vence,
                            monto_base=contrato.monto_renta,
                            concepto=f"Renta de {nombre_mes} {hoy.year}",
                            estado='PENDIENTE'
                        )
                        facturas_creadas += 1
                        numero_apto = getattr(contrato.apartamento, 'numero_unidad', 'N/A') if getattr(contrato, 'apartamento', None) else 'N/A'
                        msg_exito = f"Factura generada con éxito: Contrato ID {contrato.id} ({nombre_inquilino} - Apt {numero_apto})"
                        self.stdout.write(self.style.SUCCESS(msg_exito))
                        logger.info(msg_exito)
                    else:
                        msg_existe = f"Contrato ID {contrato.id} ya tiene factura procesada este mes."
                        self.stdout.write(msg_existe)
                        logger.info(msg_existe)

            except Exception as e:
                msg_error = f"Fallo en contrato ID {contrato.id} ({nombre_inquilino}): {str(e)}"
                self.stdout.write(self.style.ERROR(msg_error))
                logger.error(msg_error, exc_info=True)

        mensaje_fin = f"Proceso terminado. Se generaron {facturas_creadas} facturas nuevas hoy."
        self.stdout.write(self.style.SUCCESS(mensaje_fin))
        logger.info(mensaje_fin)
