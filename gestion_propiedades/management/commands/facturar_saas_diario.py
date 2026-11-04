from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
import calendar
import decimal
from django.db import transaction
from django.contrib.auth.models import User
from gestion_propiedades.models import Propiedad, FacturaSaaS, Contrato, Factura, CargoMora, AccesoPortafolio, RegistroProceso, CargoAdicionalContrato, DetalleFacturaServicio
from gestion_propiedades.utils import obtener_nombre_mes
from gestion_propiedades.utils_correo import (
    enviar_aviso_factura_saas,
    enviar_recordatorio_factura_saas,
    enviar_aviso_suspension_saas,
    enviar_aviso_factura_generada, 
    enviar_aviso_vencimiento_cercano, 
    enviar_aviso_mora_aplicada,
    enviar_aviso_trial_por_vencer,
    enviar_aviso_trial_vencido,
    enviar_reporte_diario_admin
)
from gestion_propiedades.utils_saas import (
    calcular_metricas_facturacion_saas,
    calcular_fecha_vencimiento_dias_habiles,
    contar_dias_habiles_entre
)

class Command(BaseCommand):
    help = 'Genera facturas SaaS, recibos de Inquilinos y aplica moras diariamente con alertas de correo.'

    def handle(self, *args, **options):
        hoy = timezone.now().date()
        self.stdout.write(self.style.SUCCESS(f"=== Iniciando Cron Job B2B/B2C + Moras | {hoy} ==="))
        
        # ---------------------------------------------------------
        # FASE 1: AUTOMATIZACIÓN SAAS (B2B) - EMISIÓN POR ADELANTADO
        # ---------------------------------------------------------
        clientes = User.objects.filter(is_superuser=False, suscripcion__isnull=False)
        facturas_saas = 0
        
        for cliente in clientes:
            suscripcion = cliente.suscripcion
            if suscripcion.estado != 'ACTIVA': continue
            if suscripcion.fecha_proximo_pago and hoy < suscripcion.fecha_proximo_pago: continue
                
            # Cálculo financiero según el plan y tarifa escalonada
            metricas = calcular_metricas_facturacion_saas(suscripcion)
            
            # Fecha de vencimiento calculada en días hábiles (Lunes a Viernes)
            dias_gracia = metricas['dias_gracia_habiles']
            fecha_venc = calcular_fecha_vencimiento_dias_habiles(hoy, dias_gracia)
            
            nueva_fs = FacturaSaaS.objects.create(
                usuario=cliente,
                fecha_vencimiento=fecha_venc,
                monto_total=metricas['monto_total'],
                propiedades_cobradas=metricas['propiedades_total'],
                usuarios_cobrados=metricas['usuarios_extra'],
                estado='PENDIENTE'
            )
            facturas_saas += 1
            suscripcion.fecha_proximo_pago = hoy + timedelta(days=30)
            suscripcion.save()
            
            # Enviar factura por adelantado al Administrador Titular
            enviar_aviso_factura_saas(nueva_fs)
                
        self.stdout.write(self.style.SUCCESS(f"[OK] SaaS (B2B): {facturas_saas} facturas a dueños emitidas."))

        # ---------------------------------------------------------
        # FASE 1.5: SEGUIMIENTO Y RECORDATORIOS DISCRETOS DE FACTURAS SAAS
        # ---------------------------------------------------------
        facturas_saas_pendientes = FacturaSaaS.objects.filter(estado='PENDIENTE').select_related('usuario', 'usuario__suscripcion')
        saas_recordatorios = 0
        saas_suspendidas = 0
        
        for fs in facturas_saas_pendientes:
            dias_habiles_restantes = contar_dias_habiles_entre(hoy, fs.fecha_vencimiento)
            
            if hoy > fs.fecha_vencimiento:
                # Plazo cumplido sin pago: Marcar vencida y suspender
                fs.estado = 'VENCIDA'
                fs.save()
                
                try:
                    sub = fs.usuario.suscripcion
                    if sub.estado == 'ACTIVA':
                        sub.estado = 'SUSPENDIDA'
                        sub.save()
                        enviar_aviso_suspension_saas(fs)
                        saas_suspendidas += 1
                except Exception:
                    pass
            elif dias_habiles_restantes in [5, 1]:
                # Recordatorio cortes (5 dias habiles) o aviso preventivo (1 dia habil)
                enviar_recordatorio_factura_saas(fs, dias_habiles_restantes)
                saas_recordatorios += 1

        if saas_recordatorios > 0 or saas_suspendidas > 0:
            self.stdout.write(self.style.SUCCESS(f"[OK] SaaS Seguimiento: {saas_recordatorios} recordatorios discretos, {saas_suspendidas} cuentas pausadas."))

        # ---------------------------------------------------------
        contratos_activos = Contrato.objects.filter(activo=True)
        facturas_b2c = 0
        errores_cron = []
        
        for contrato in contratos_activos:
            try:
                ultimo_dia_mes = calendar.monthrange(hoy.year, hoy.month)[1]
                dia_cobro_efectivo = min(contrato.dia_de_pago, ultimo_dia_mes)
                
                if hoy.day >= dia_cobro_efectivo:
                    ya_facturado = Factura.objects.filter(
                        contrato=contrato, fecha_emision__year=hoy.year, fecha_emision__month=hoy.month
                    ).exists()
                    
                    if not ya_facturado:
                        cargos_activos = list(contrato.cargos_adicionales.filter(activo=True))
                        monto_servicios = sum(c.monto for c in cargos_activos)
                        monto_renta = contrato.monto_renta
                        total_base = monto_renta + monto_servicios
                        concepto_cron = contrato.propiedad.portafolio.generar_concepto_factura(contrato, hoy)
                        nueva_fact = Factura.objects.create(
                            contrato=contrato,
                            fecha_emision=hoy,
                            fecha_vencimiento=hoy + timedelta(days=contrato.dias_gracia),
                            monto_base=total_base,
                            monto_renta=monto_renta,
                            monto_servicios=monto_servicios,
                            estado='PENDIENTE',
                            concepto=concepto_cron
                        )
                        for c in cargos_activos:
                            DetalleFacturaServicio.objects.create(
                                factura=nueva_fact,
                                cargo_origen=c,
                                categoria=c.categoria,
                                concepto=c.nombre_mostrar,
                                monto=c.monto
                            )
                        facturas_b2c += 1
                        
                        # Enviar estado de cuenta Inquilino
                        enviar_aviso_factura_generada(nueva_fact)
            except Exception as e:
                errores_cron.append(f"Error en contrato {contrato.id} ({contrato.inquilino.nombre}): {str(e)}")
                    
        exitoso = len(errores_cron) == 0
        detalles = f"Proceso diario ejecutado. Se crearon {facturas_b2c} facturas B2C."
        if errores_cron:
            detalles += "\nErrores detectados:\n" + "\n".join(errores_cron)
            
        RegistroProceso.objects.create(
            nombre_proceso="Generación de Rentas (Cron)",
            exitoso=exitoso,
            facturas_creadas=facturas_b2c,
            detalles=detalles
        )

        self.stdout.write(self.style.SUCCESS(f"[OK] Rentas (B2C): {facturas_b2c} recibos emitidos a inquilinos."))

        # ---------------------------------------------------------
        # FASE 3: MOTOR DE MORAS Y RECORDATORIOS
        # La mora continúa calculándose mensualmente hasta que el monto del alquiler esté saldado
        # ---------------------------------------------------------
        facturas_pendientes = Factura.objects.filter(
            estado__in=['PENDIENTE', 'ATRASADA']
        ).select_related('contrato', 'contrato__inquilino')
        recordatorios = 0
        moras = 0
        
        for factura in facturas_pendientes:
            contrato = factura.contrato
            
            # Si el saldo de alquiler ya está saldado (saldo_renta_pendiente <= 0), no se cobra más mora
            if factura.saldo_renta_pendiente <= decimal.Decimal('0.00'):
                if factura.saldo_pendiente <= decimal.Decimal('0.00') and factura.estado != 'PAGADA':
                    factura.estado = 'PAGADA'
                    factura.save()
                continue
                
            # 3.1 Aviso preventivo
            if factura.estado == 'PENDIENTE' and hoy == factura.fecha_vencimiento - timedelta(days=1):
                enviar_aviso_vencimiento_cercano(factura)
                recordatorios += 1
                
            # 3.2 Aplicación de Mora Matemática y Cambio a Atrasada
            elif hoy > factura.fecha_vencimiento:
                # Verificar que no se haya aplicado ya la mora en este mes calendario a esta factura
                ya_cobrada_este_mes = CargoMora.objects.filter(
                    factura=factura,
                    mes_aplicado=hoy.month,
                    anio_aplicado=hoy.year
                ).exists()

                if not ya_cobrada_este_mes:
                    with transaction.atomic():
                        porcentaje = contrato.porcentaje_mora or decimal.Decimal('0.00')
                        factor = porcentaje / decimal.Decimal('100.0')
                        # La mora se calcula sobre el saldo insoluto de alquiler pendiente
                        monto_castigo = round(factura.saldo_renta_pendiente * factor, 2)
                        
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
        
        # Enviar REPORTE EJECUTIVO AL ADMIN
        try:
            estadisticas = {
                'fecha': hoy.strftime("%d/%m/%Y"),
                'facturas_saas': facturas_saas,
                'facturas_b2c': facturas_b2c,
                'recordatorios': recordatorios,
                'moras': moras,
                'trials_avisados': trials_avisados,
                'trials_suspendidos': trials_suspendidos
            }
            enviar_reporte_diario_admin(estadisticas)
            self.stdout.write(self.style.SUCCESS("[OK] Reporte B2B enviado exitosamente al SuperAdmin."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"[FAIL] Error despachando reporte administrador: {e}"))
            
        self.stdout.write(self.style.SUCCESS("=== Robot Finalizado de Manera Segura ==="))
