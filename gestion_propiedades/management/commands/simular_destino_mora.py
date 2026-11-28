from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from django.core.management.base import BaseCommand, CommandError
from gestion_propiedades.models import Portafolio, ReciboPago, LiquidacionPropietario


def _calcular_reparto_simulado(monto_mora, destino, pct_agencia):
    mora = Decimal(str(monto_mora or '0.00')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    if mora <= Decimal('0.00'):
        return Decimal('0.00'), Decimal('0.00')
    if destino == 'AGENCIA':
        return Decimal('0.00'), mora
    if destino == 'COMPARTIDA':
        m_ag = (mora * pct_agencia / Decimal('100.00')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        return mora - m_ag, m_ag
    return mora, Decimal('0.00')


class Command(BaseCommand):
    help = (
        'Simula en modo solo lectura cuánto de la mora cobrada cambiaría de propietario a agencia '
        'y qué liquidaciones abiertas (PENDIENTE) se verían afectadas.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--agencia',
            type=str,
            required=False,
            help='ID numérico o nombre (parcial) de la agencia / portafolio.',
        )
        parser.add_argument(
            '--portafolio-id',
            type=int,
            required=False,
            help='ID del portafolio (alias de --agencia).',
        )
        parser.add_argument(
            '--desde',
            type=str,
            required=True,
            help='Fecha inicial del rango (YYYY-MM-DD).',
        )
        parser.add_argument(
            '--hasta',
            type=str,
            required=True,
            help='Fecha final del rango (YYYY-MM-DD).',
        )
        parser.add_argument(
            '--destino',
            type=str,
            default='AGENCIA',
            choices=['PROPIETARIO', 'AGENCIA', 'COMPARTIDA'],
            help='Política a simular: PROPIETARIO, AGENCIA o COMPARTIDA.',
        )
        parser.add_argument(
            '--porcentaje-agencia',
            type=str,
            default='0.00',
            help='Porcentaje de mora para la agencia (0 a 100) cuando --destino=COMPARTIDA.',
        )

    def handle(self, *args, **options):
        portafolio = self._resolver_portafolio(options.get('agencia'), options.get('portafolio_id'))

        try:
            fecha_desde = datetime.strptime(options['desde'], '%Y-%m-%d').date()
            fecha_hasta = datetime.strptime(options['hasta'], '%Y-%m-%d').date()
        except ValueError:
            raise CommandError('Las fechas --desde y --hasta deben tener formato YYYY-MM-DD.')

        if fecha_desde > fecha_hasta:
            raise CommandError('La fecha --desde no puede ser posterior a --hasta.')

        destino = options['destino']
        try:
            pct_agencia = Decimal(str(options['porcentaje_agencia']))
        except Exception:
            raise CommandError('El valor de --porcentaje-agencia debe ser numérico.')

        if destino == 'COMPARTIDA' and (pct_agencia < Decimal('0.00') or pct_agencia > Decimal('100.00')):
            raise CommandError('--porcentaje-agencia debe estar entre 0 y 100.')
        if destino == 'AGENCIA':
            pct_agencia = Decimal('100.00')
        elif destino == 'PROPIETARIO':
            pct_agencia = Decimal('0.00')

        recibos = ReciboPago.objects.filter(
            factura__contrato__propiedad__portafolio=portafolio,
            fecha_pago__range=[fecha_desde, fecha_hasta],
            estado='ACTIVO',
        ).select_related(
            'factura',
            'factura__contrato',
            'factura__contrato__propiedad',
            'factura__contrato__propiedad__propietario_inmueble',
        )

        total_mora_cobrada = Decimal('0.00')
        actual_prop = Decimal('0.00')
        actual_ag = Decimal('0.00')
        sim_prop = Decimal('0.00')
        sim_ag = Decimal('0.00')
        cambio_por_periodo_prop = {}

        for r in recibos:
            mora_r = Decimal(str(r.monto_a_mora or '0.00'))
            if mora_r <= Decimal('0.00'):
                continue

            total_mora_cobrada += mora_r
            cur_p = r.mora_para_propietario
            cur_a = r.mora_para_agencia
            actual_prop += cur_p
            actual_ag += cur_a

            prop_inm = r.factura.contrato.propiedad.propietario_inmueble
            if prop_inm and prop_inm.politica_mora != 'USAR_AGENCIA':
                dest_ef, pct_ef = prop_inm.obtener_politica_mora_efectiva()
            else:
                dest_ef, pct_ef = destino, pct_agencia

            new_p, new_a = _calcular_reparto_simulado(mora_r, dest_ef, pct_ef)
            sim_prop += new_p
            sim_ag += new_a

            if prop_inm:
                key = (prop_inm.id, r.fecha_pago.month, r.fecha_pago.year)
                cambio_por_periodo_prop[key] = cambio_por_periodo_prop.get(key, Decimal('0.00')) + (new_a - cur_a)

        cambio_prop_a_agencia = sim_ag - actual_ag

        # Evaluar liquidaciones abiertas (PENDIENTE) y cerradas (PAGADO) afectadas en los períodos del rango
        meses_en_rango = self._meses_en_rango(fecha_desde, fecha_hasta)
        liquidaciones_abiertas_afectadas = []
        liquidaciones_cerradas_en_rango = 0

        liqs = LiquidacionPropietario.objects.filter(
            propietario_inmueble__portafolio=portafolio,
        ).select_related('propietario_inmueble')

        for liq in liqs:
            if (liq.periodo_anio, liq.periodo_mes) not in meses_en_rango:
                continue
            if liq.estado == 'PAGADO':
                liquidaciones_cerradas_en_rango += 1
                continue
            key = (liq.propietario_inmueble_id, liq.periodo_mes, liq.periodo_anio)
            delta = cambio_por_periodo_prop.get(key, Decimal('0.00'))
            if delta != Decimal('0.00'):
                liquidaciones_abiertas_afectadas.append((liq, delta))

        self.stdout.write(self.style.MIGRATE_HEADING(f"=== Simulación de Destino de Mora (Solo Lectura) ==="))
        self.stdout.write(f"Agencia: {portafolio.nombre} (ID {portafolio.id})")
        self.stdout.write(f"Período: {fecha_desde} al {fecha_hasta}")
        self.stdout.write(f"Política simulada: {destino} ({pct_agencia:.2f}% agencia)")
        self.stdout.write(f"Recibos activos evaluados: {recibos.count()}")
        self.stdout.write(f"Total mora cobrada en el rango: RD$ {total_mora_cobrada:,.2f}")
        self.stdout.write(f"Actual -> Propietario: RD$ {actual_prop:,.2f} | Agencia: RD$ {actual_ag:,.2f}")
        self.stdout.write(f"Simulado -> Propietario: RD$ {sim_prop:,.2f} | Agencia: RD$ {sim_ag:,.2f}")
        self.stdout.write(self.style.SUCCESS(
            f"Monto que cambiaría de propietario a agencia: RD$ {cambio_prop_a_agencia:,.2f}"
        ))

        if liquidaciones_abiertas_afectadas:
            self.stdout.write(self.style.WARNING(
                f"Liquidaciones abiertas (PENDIENTE) afectadas: {len(liquidaciones_abiertas_afectadas)}"
            ))
            for liq, delta in liquidaciones_abiertas_afectadas:
                self.stdout.write(
                    f"  - Liquidación #{liq.id} | {liq.propietario_inmueble.nombre} | "
                    f"{liq.periodo_mes:02d}/{liq.periodo_anio} | Cambio a agencia: RD$ {delta:,.2f}"
                )
        else:
            self.stdout.write("Liquidaciones abiertas (PENDIENTE) afectadas: 0")

        self.stdout.write(
            f"Liquidaciones cerradas/pagadas en el rango (no se modifican): {liquidaciones_cerradas_en_rango}"
        )

    def _resolver_portafolio(self, agencia, portafolio_id):
        if portafolio_id is not None:
            p = Portafolio.objects.filter(id=portafolio_id).first()
            if not p:
                raise CommandError(f'No existe ningún portafolio con ID {portafolio_id}.')
            return p
        if agencia:
            if str(agencia).isdigit():
                p = Portafolio.objects.filter(id=int(agencia)).first()
                if p:
                    return p
            qs = Portafolio.objects.filter(nombre__icontains=agencia)
            if qs.count() == 1:
                return qs.first()
            if qs.count() > 1:
                nombres = ', '.join(f"{p.id}:{p.nombre}" for p in qs)
                raise CommandError(f"Múltiples agencias coinciden con '{agencia}': {nombres}. Usa --portafolio-id.")
            raise CommandError(f"No se encontró ninguna agencia que coincida con '{agencia}'.")
        raise CommandError('Debes especificar --agencia o --portafolio-id.')

    @staticmethod
    def _meses_en_rango(desde, hasta):
        res = set()
        y, m = desde.year, desde.month
        while (y, m) <= (hasta.year, hasta.month):
            res.add((y, m))
            if m == 12:
                y += 1
                m = 1
            else:
                m += 1
        return res
