from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
import calendar
import decimal
from django.db import transaction
from django.contrib.auth.models import User
from gestion_propiedades.models import Propiedad, FacturaSaaS, Contrato, Factura, CargoMora
from gestion_propiedades.utils_correo import (
    enviar_aviso_factura_saas, 
    enviar_aviso_factura_generada, 
    enviar_aviso_vencimiento_cercano, 
    enviar_aviso_mora_aplicada,
    enviar_aviso_trial_por_vencer,
    enviar_aviso_trial_vencido
)

class Command(BaseCommand):
    help = 'Genera facturas SaaS, recibos de Inquilinos y aplica moras diariamente con alertas de correo.'

    def handle(self, *args, **options):
        hoy = timezone.now().date()
        self.stdout.write(self.style.SUCCESS(f"=== Iniciando Cron Job B2B/B2C + Moras | {hoy} ==="))
        
        # ---------------------------------------------------------
        # FASE 1: AUTOMATIZACIÓN SAAS (B2B)
        # ---------------------------------------------------------
        clientes = User.objects.filter(is_superuser=False, suscripcion__isnull=False)
        facturas_saas = 0
        
        for cliente in clientes:
            suscripcion = cliente.suscripcion
            if suscripcion.estado != 'ACTIVA': continue
            if suscripcion.fecha_proximo_pago and hoy < suscripcion.fecha_proximo_pago: continue
                
            cant_propiedades = Propiedad.objects.filter(portafolio__propietario=cliente, is_deleted=False).count()
            
            if cant_propiedades > 0:
                monto = cant_propiedades * 1.00
                nueva_fs = FacturaSaaS.objects.create(
                    usuario=cliente,
                    fecha_vencimiento=hoy + timedelta(days=5),
                    monto_total=monto,
                    propiedades_cobradas=cant_propiedades,
                    estado='PENDIENTE'
                )
                facturas_saas += 1
                suscripcion.fecha_proximo_pago = hoy + timedelta(days=30)
                suscripcion.save()
                
                # Enviar recibo B2B
                enviar_aviso_factura_saas(nueva_fs)
                
        self.stdout.write(self.style.SUCCESS(f"[OK] SaaS (B2B): {facturas_saas} facturas a dueños emitidas."))

        # ---------------------------------------------------------
        # FASE 2: AUTOMATIZACIÓN DE RENTAS INQUILINOS (B2C)
        # ---------------------------------------------------------
        contratos_activos = Contrato.objects.filter(activo=True)
        facturas_b2c = 0
        
        for contrato in contratos_activos:
            ultimo_dia_mes = calendar.monthrange(hoy.year, hoy.month)[1]
            dia_cobro_efectivo = min(contrato.dia_de_pago, ultimo_dia_mes)
            
            if hoy.day >= dia_cobro_efectivo:
                ya_facturado = Factura.objects.filter(
                    contrato=contrato, fecha_emision__year=hoy.year, fecha_emision__month=hoy.month
                ).exists()
                
                if not ya_facturado:
                    nueva_fact = Factura.objects.create(
                        contrato=contrato,
                        fecha_emision=hoy,
                        fecha_vencimiento=hoy + timedelta(days=contrato.dias_gracia),
                        monto_base=contrato.monto_renta,
                        estado='PENDIENTE',
                        concepto=f'Renta mensual ({hoy.strftime("%m/%Y")})'
                    )
                    facturas_b2c += 1
                    
                    # Enviar estado de cuenta Inquilino
                    enviar_aviso_factura_generada(nueva_fact)
                    
        self.stdout.write(self.style.SUCCESS(f"[OK] Rentas (B2C): {facturas_b2c} recibos emitidos a inquilinos."))

        # ---------------------------------------------------------
        # FASE 3: MOTOR DE MORAS Y RECORDATORIOS
        # ---------------------------------------------------------
        facturas_pendientes = Factura.objects.filter(estado='PENDIENTE').select_related('contrato', 'contrato__inquilino')
        recordatorios = 0
        moras = 0
        
        for factura in facturas_pendientes:
            contrato = factura.contrato
            
            # 3.1 Aviso preventivo
            if hoy == factura.fecha_vencimiento - timedelta(days=1):
                enviar_aviso_vencimiento_cercano(factura)
                recordatorios += 1
                
            # 3.2 Aplicación de Mora Matemática y Cambio a Atrasada
            elif hoy > factura.fecha_vencimiento:
                with transaction.atomic():
                    porcentaje = contrato.porcentaje_mora or decimal.Decimal('0.00')
                    factor = porcentaje / decimal.Decimal('100.0')
                    monto_castigo = round(factura.monto_base * factor, 2)
                    
                    mora_obj = None
                    if monto_castigo > 0:
                        mora_obj = CargoMora.objects.create(
                            factura=factura,
                            monto=monto_castigo,
                            mes_aplicado=hoy.month,
                            anio_aplicado=hoy.year
                        )
                    
                    factura.estado = 'ATRASADA'
                    factura.save()
                    moras += 1
                    
                    # Avisamos de la mala noticia
                    if mora_obj:
                        enviar_aviso_mora_aplicada(factura, mora_obj)

        # ---------------------------------------------------------
        # FASE 4: CICLO DE VIDA DE CUENTAS TRIAL (B2B SaaS)
        # ---------------------------------------------------------
        trials_avisados = 0
        trials_suspendidos = 0
        
        # Escaneamos propietarios cuyo estado es TRIAL
        clientes_trial = User.objects.filter(suscripcion__estado='TRIAL').select_related('suscripcion')
        
        for cliente in clientes_trial:
            sub = cliente.suscripcion
            if not sub.fecha_proximo_pago:
                continue
                
            # ¿Quedan exactamente 3 días para vencer?
            if hoy == sub.fecha_proximo_pago - timedelta(days=3):
                enviar_aviso_trial_por_vencer(cliente, dias=3)
                trials_avisados += 1
                
            # ¿Vencido? (Si expiró hoy o un día anterior por error)
            elif hoy >= sub.fecha_proximo_pago:
                sub.estado = 'SUSPENDIDA'
                sub.save()
                enviar_aviso_trial_vencido(cliente)
                trials_suspendidos += 1
                
        self.stdout.write(self.style.SUCCESS(f"[OK] Trials B2B: {trials_avisados} alertas enviadas, {trials_suspendidos} cancelados."))

        self.stdout.write(self.style.SUCCESS(f"[OK] Alertas B2C: {recordatorios} recordatorios de vencimiento enviados."))
        self.stdout.write(self.style.SUCCESS(f"[OK] Morosidad B2C: {moras} penalizaciones aplicadas exitosamente."))
        self.stdout.write(self.style.SUCCESS("=== Robot Finalizado de Manera Segura ==="))
