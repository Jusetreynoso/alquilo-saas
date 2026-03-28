from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth.models import User
from gestion_propiedades.models import Propiedad, FacturaSaaS, Contrato, Factura
import calendar

class Command(BaseCommand):
    help = 'Genera facturas SaaS (B2B) y recibos de Rentas de Inquilinos (B2C) diariamente.'

    def handle(self, *args, **options):
        hoy = timezone.now().date()
        self.stdout.write(self.style.SUCCESS(f"=== Iniciando Cron Job de Facturación | {hoy} ==="))
        
        # ---------------------------------------------------------
        # FASE 1: AUTOMATIZACIÓN SAAS (B2B)
        # ---------------------------------------------------------
        clientes = User.objects.filter(is_superuser=False, suscripcion__isnull=False)
        facturas_saas = 0
        
        for cliente in clientes:
            suscripcion = cliente.suscripcion
            
            if suscripcion.estado != 'ACTIVA':
                continue
            if suscripcion.fecha_proximo_pago and hoy < suscripcion.fecha_proximo_pago:
                continue
                
            cant_propiedades = Propiedad.objects.filter(
                portafolio__propietario=cliente,
                is_deleted=False
            ).count()
            
            if cant_propiedades > 0:
                monto = cant_propiedades * 1.00
                FacturaSaaS.objects.create(
                    usuario=cliente,
                    fecha_vencimiento=hoy + timedelta(days=5),
                    monto_total=monto,
                    propiedades_cobradas=cant_propiedades,
                    estado='PENDIENTE'
                )
                facturas_saas += 1
                suscripcion.fecha_proximo_pago = hoy + timedelta(days=30)
                suscripcion.save()
                
        self.stdout.write(self.style.SUCCESS(f"[OK] SaaS (B2B): {facturas_saas} facturas a clientes creadas."))

        # ---------------------------------------------------------
        # FASE 2: AUTOMATIZACIÓN DE RENTAS INQUILINOS (B2C)
        # ---------------------------------------------------------
        contratos_activos = Contrato.objects.filter(activo=True)
        facturas_b2c = 0
        
        for contrato in contratos_activos:
            # Ajuste inteligente para meses cortos (Ej, Febrero 28 vs Dia de pago 31)
            ultimo_dia_mes = calendar.monthrange(hoy.year, hoy.month)[1]
            dia_cobro_efectivo = min(contrato.dia_de_pago, ultimo_dia_mes)
            
            # Verificar si hoy es el día de cobro o superior (por si el cron no corrió ayer)
            if hoy.day >= dia_cobro_efectivo:
                # Poliza Anti-Duplicados: ¿Ya le facturamos a este inquilino en ESTE mes y año exacto?
                ya_facturado = Factura.objects.filter(
                    contrato=contrato, 
                    fecha_emision__year=hoy.year, 
                    fecha_emision__month=hoy.month
                ).exists()
                
                if not ya_facturado:
                    Factura.objects.create(
                        contrato=contrato,
                        fecha_emision=hoy,
                        fecha_vencimiento=hoy + timedelta(days=contrato.dias_gracia),
                        monto_base=contrato.monto_renta,
                        estado='PENDIENTE',
                        concepto=f'Renta mensual ({hoy.strftime("%m/%Y")})'
                    )
                    facturas_b2c += 1
                    
        self.stdout.write(self.style.SUCCESS(f"[OK] Rentas (B2C): {facturas_b2c} recibos de alquiler emitidos a inquilinos."))
        self.stdout.write(self.style.SUCCESS("=== Robot Finalizado ==="))
