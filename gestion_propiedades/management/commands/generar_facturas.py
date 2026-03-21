from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from gestion_propiedades.models import Contrato, Factura

class Command(BaseCommand):
    help = 'Genera facturas automáticas para los contratos en su día de cobro'

    def handle(self, *args, **kwargs):
        hoy = timezone.now().date()
        dia_actual = hoy.day
        
        # Diccionario simple para traducir el mes al español en el concepto
        meses_espanol = {
            1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril', 5: 'Mayo', 6: 'Junio',
            7: 'Julio', 8: 'Agosto', 9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'
        }

        self.stdout.write(f"Iniciando revisión de facturación para el día {dia_actual}...")

        # Buscamos contratos activos cuyo día de pago sea hoy
        contratos = Contrato.objects.filter(activo=True, dia_de_pago=dia_actual)
        facturas_creadas = 0

        for contrato in contratos:
            # Validación de seguridad: Verificar que no hayamos facturado este mes ya
            factura_existe = Factura.objects.filter(
                contrato=contrato,
                fecha_emision__year=hoy.year,
                fecha_emision__month=hoy.month
            ).exists()

            if not factura_existe:
                # Damos 5 días de gracia para el vencimiento
                fecha_vence = hoy + timedelta(days=5)
                nombre_mes = meses_espanol[hoy.month]

                Factura.objects.create(
                    contrato=contrato,
                    fecha_emision=hoy,
                    fecha_vencimiento=fecha_vence,
                    monto_total=contrato.monto_renta,
                    concepto=f"Renta de {nombre_mes} {hoy.year}",
                    estado='PENDIENTE'
                )
                facturas_creadas += 1
                self.stdout.write(self.style.SUCCESS(f'Factura creada para: {contrato.inquilino.nombre_completo} - Apt {contrato.apartamento.numero_unidad}'))

        self.stdout.write(self.style.SUCCESS(f'Proceso terminado. Se generaron {facturas_creadas} facturas nuevas.'))