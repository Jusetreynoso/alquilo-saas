import csv
import sys
from decimal import Decimal
from datetime import timedelta
from collections import defaultdict
from django.core.management.base import BaseCommand
from django.utils import timezone
from gestion_propiedades.models import Factura, ReciboPago, Portafolio


class Command(BaseCommand):
    help = (
        "Comando de SOLO LECTURA para auditar y detectar cobros duplicados y sobrepagos. "
        "Lista por tenant las facturas con pagos superiores a su total y recibos sospechosos en ventanas cortas."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--portafolio_id',
            type=int,
            default=None,
            help='Filtrar auditoría por ID de un Portafolio / Tenant específico.'
        )
        parser.add_argument(
            '--csv',
            type=str,
            default=None,
            help='Ruta del archivo CSV para exportar los hallazgos (ej: duplicados.csv).'
        )
        parser.add_argument(
            '--horas',
            type=int,
            default=48,
            help='Ventana de tiempo en horas para detectar pagos idénticos sospechosos (por defecto: 48).'
        )

    def handle(self, *args, **options):
        portafolio_id = options.get('portafolio_id')
        csv_path = options.get('csv')
        horas_ventana = options.get('horas', 48)

        self.stdout.write(self.style.MIGRATE_HEADING("=== AUDITORÍA DE PAGOS DUPLICADOS Y SOBREPAGOS (SOLO LECTURA) ==="))

        portafolios_qs = Portafolio.objects.all().order_by('nombre')
        if portafolio_id:
            portafolios_qs = portafolios_qs.filter(id=portafolio_id)
            if not portafolios_qs.exists():
                self.stderr.write(self.style.ERROR(f"No se encontró el portafolio con ID {portafolio_id}."))
                return

        registros_csv = []
        total_sobrepagos_detectados = 0
        total_duplicados_sospechosos = 0

        for portafolio in portafolios_qs:
            self.stdout.write(f"\n🏢 Portafolio #{portafolio.id}: {portafolio.nombre} (Dueño: {portafolio.propietario.username})")

            # 1. Facturas con pagos mayores a su monto total con mora
            facturas_portafolio = Factura.objects.filter(
                contrato__propiedad__portafolio=portafolio
            ).select_related('contrato__inquilino', 'contrato__propiedad').prefetch_related('recibos')

            sobrepagos_port = []
            for f in facturas_portafolio:
                pagado_activo = f.monto_pagado_total
                total_con_mora = f.monto_total_con_mora
                if pagado_activo > total_con_mora:
                    exceso = pagado_activo - total_con_mora
                    sobrepagos_port.append((f, total_con_mora, pagado_activo, exceso))

            if sobrepagos_port:
                self.stdout.write(self.style.WARNING(f"   ⚠️ Facturas con sobrepago detectadas: {len(sobrepagos_port)}"))
                for f, tot, pag, diff in sobrepagos_port:
                    total_sobrepagos_detectados += 1
                    inquilino_nom = f.contrato.inquilino.nombre if f.contrato and f.contrato.inquilino else 'Desconocido'
                    prop_nom = f.contrato.propiedad.nombre_o_numero if f.contrato and f.contrato.propiedad else 'S/P'
                    recibos_activos = list(f.recibos.filter(estado='ACTIVO').order_by('id'))
                    ids_recibos = ", ".join([f"#{r.id} (RD${r.monto_pagado:,.2f})" for r in recibos_activos])

                    self.stdout.write(
                        f"      • Factura #{f.id} [{prop_nom} | Inquilino: {inquilino_nom}]: "
                        f"Total facturado: RD$ {tot:,.2f} | Total cobrado: RD$ {pag:,.2f} | "
                        f"Exceso: RD$ {diff:,.2f} | Recibos: {ids_recibos}"
                    )

                    for r in recibos_activos:
                        registros_csv.append({
                            'Tipo_Hallazgo': 'SOBREPAGO_FACTURA',
                            'Portafolio_ID': portafolio.id,
                            'Portafolio_Nombre': portafolio.nombre,
                            'Contrato_ID': f.contrato_id,
                            'Inquilino': inquilino_nom,
                            'Propiedad': prop_nom,
                            'Factura_ID': f.id,
                            'Total_Factura': tot,
                            'Total_Cobrado': pag,
                            'Exceso_Cobrado': diff,
                            'Recibo_ID': r.id,
                            'Fecha_Pago': r.fecha_pago,
                            'Monto_Recibo': r.monto_pagado,
                            'Metodo_Pago': r.metodo_pago,
                            'Referencia': r.referencia_transaccion or '',
                            'Registrado_Por': r.registrado_por.username if r.registrado_por else 'N/A',
                            'Registrado_En': r.registrado_en,
                        })
            else:
                self.stdout.write(self.style.SUCCESS("   ✓ Sin facturas con sobrepago."))

            # 2. Recibos duplicados en el mismo contrato con monto idéntico en ventana corta
            recibos_portafolio = ReciboPago.objects.filter(
                factura__contrato__propiedad__portafolio=portafolio,
                estado='ACTIVO'
            ).select_related('factura__contrato__inquilino', 'factura__contrato__propiedad', 'registrado_por').order_by('fecha_pago', 'registrado_en')

            grupos_duplicados = defaultdict(list)
            for r in recibos_portafolio:
                ref_limpia = (r.referencia_transaccion or '').strip().upper()
                grupos_duplicados[(r.factura.contrato_id, r.monto_pagado)].append(r)

            sospechosos_port = []
            for (c_id, monto), r_list in grupos_duplicados.items():
                if len(r_list) > 1:
                    # Verificar si coinciden en referencia idéntica o en fecha de pago similar
                    for i in range(len(r_list)):
                        for j in range(i + 1, len(r_list)):
                            r1 = r_list[i]
                            r2 = r_list[j]
                            mismo_dia = r1.fecha_pago == r2.fecha_pago
                            misma_ref = bool(r1.referencia_transaccion and r2.referencia_transaccion and r1.referencia_transaccion.strip().upper() == r2.referencia_transaccion.strip().upper())
                            diferencia_horas = abs((r2.registrado_en - r1.registrado_en).total_seconds()) / 3600.0 if (r1.registrado_en and r2.registrado_en) else 999.0

                            if misma_ref or mismo_dia or diferencia_horas <= horas_ventana:
                                sospechosos_port.append((r1, r2, c_id, monto, misma_ref, diferencia_horas))

            if sospechosos_port:
                self.stdout.write(self.style.WARNING(f"   ⚠️ Pagos duplicados sospechosos (mismo contrato y monto): {len(sospechosos_port)} pares"))
                for r1, r2, c_id, monto, misma_ref, diff_h in sospechosos_port:
                    total_duplicados_sospechosos += 1
                    motivo = "Misma Referencia" if misma_ref else f"Ventana de {diff_h:.1f}h / Mismo Día"
                    self.stdout.write(
                        f"      • Contrato #{c_id} [Monto: RD$ {monto:,.2f}]: "
                        f"Recibo #{r1.id} (Factura #{r1.factura_id}, {r1.fecha_pago}) vs "
                        f"Recibo #{r2.id} (Factura #{r2.factura_id}, {r2.fecha_pago}) | Criterio: {motivo}"
                    )
                    registros_csv.append({
                        'Tipo_Hallazgo': 'RECIBO_DUPLICADO_SOSPECHOSO',
                        'Portafolio_ID': portafolio.id,
                        'Portafolio_Nombre': portafolio.nombre,
                        'Contrato_ID': c_id,
                        'Inquilino': r1.factura.contrato.inquilino.nombre if r1.factura.contrato and r1.factura.contrato.inquilino else 'Desconocido',
                        'Propiedad': r1.factura.contrato.propiedad.nombre_o_numero if r1.factura.contrato and r1.factura.contrato.propiedad else 'S/P',
                        'Factura_ID': f"{r1.factura_id} / {r2.factura_id}",
                        'Total_Factura': 'N/A',
                        'Total_Cobrado': 'N/A',
                        'Exceso_Cobrado': monto,
                        'Recibo_ID': f"#{r1.id} vs #{r2.id}",
                        'Fecha_Pago': f"{r1.fecha_pago} / {r2.fecha_pago}",
                        'Monto_Recibo': monto,
                        'Metodo_Pago': f"{r1.metodo_pago} / {r2.metodo_pago}",
                        'Referencia': f"'{r1.referencia_transaccion}' vs '{r2.referencia_transaccion}'",
                        'Registrado_Por': f"{r1.registrado_por} / {r2.registrado_por}",
                        'Registrado_En': f"{r1.registrado_en} / {r2.registrado_en}",
                    })
            else:
                self.stdout.write(self.style.SUCCESS("   ✓ Sin pagos duplicados sospechosos en ventana de tiempo."))

        self.stdout.write("\n" + "=" * 65)
        self.stdout.write(f"Total Facturas con Sobrepago encontradas: {total_sobrepagos_detectados}")
        self.stdout.write(f"Total Pares de Recibos Sospechosos: {total_duplicados_sospechosos}")
        self.stdout.write("=" * 65)

        if csv_path:
            fieldnames = [
                'Tipo_Hallazgo', 'Portafolio_ID', 'Portafolio_Nombre', 'Contrato_ID',
                'Inquilino', 'Propiedad', 'Factura_ID', 'Total_Factura', 'Total_Cobrado',
                'Exceso_Cobrado', 'Recibo_ID', 'Fecha_Pago', 'Monto_Recibo', 'Metodo_Pago',
                'Referencia', 'Registrado_Por', 'Registrado_En'
            ]
            try:
                with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    for r in registros_csv:
                        writer.writerow(r)
                self.stdout.write(self.style.SUCCESS(f"\n[OK] Reporte exportado exitosamente a CSV: {csv_path}"))
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"Error al escribir CSV en {csv_path}: {e}"))
