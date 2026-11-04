"""
Script de Importación Masiva para la Cartera de Basora & Arriaga (132 Inmuebles)
Ejecutar con:
  python importar_cartera_basora.py           (Modo Simulación / Dry-Run)
  python importar_cartera_basora.py --commit  (Modo Real / Guarda en Base de Datos)
"""

import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

import csv
import re
from datetime import datetime, date
from decimal import Decimal

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'alquilo_core.settings')
django.setup()

from django.db import transaction
from django.contrib.auth.models import User
from django.utils import timezone
from gestion_propiedades.models import (
    Portafolio,
    PropietarioInmueble,
    Propiedad,
    Inquilino,
    Contrato,
    PlanSaaS,
    SuscripcionCliente,
    CargoAdicionalContrato
)


def parse_decimal(val, default="0.00"):
    if not val:
        return Decimal(default)
    val_clean = re.sub(r'[^\d.]', '', str(val).replace(',', ''))
    try:
        return Decimal(val_clean) if val_clean else Decimal(default)
    except Exception:
        return Decimal(default)


def parse_fecha(val):
    if not val:
        return None
    val = str(val).strip()
    if val.upper() in ['N/A', 'NA', 'NO', 'NO SE LE HA HECHO']:
        return None
    
    # Probar YYYY-MM-DD
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%Y/%m/%d'):
        try:
            return datetime.strptime(val, fmt).date()
        except ValueError:
            pass
    return None


def parse_dia_pago(val):
    if not val:
        return 30
    match = re.search(r'\d+', str(val))
    if match:
        day = int(match.group(0))
        if 1 <= day <= 31:
            return day
    return 30


def limpiar_texto(val):
    if not val:
        return ""
    txt = str(val).strip()
    if txt.upper() in ['N/A', 'NA', 'NULL', 'NONE']:
        return ""
    return txt


def limpiar_telefono(val):
    if not val:
        return ""
    txt = str(val).strip()
    if txt.upper() in ['N/A', 'NA', 'NULL', 'NONE']:
        return ""
    # Si viene con múltiples números (ej: (829) 677-0676 / (809)-863-9982), tomar el principal
    if '/' in txt:
        txt = txt.split('/')[0].strip()
    if ',' in txt:
        txt = txt.split(',')[0].strip()
    return txt[:20].strip()


def ejecutar_importacion(csv_path='cartera_basora_arriaga.csv', email_cliente='lbasora@basoraarriaga.com', commit=False):
    print("=" * 70)
    print("🚀 INICIANDO IMPORTACIÓN MASIVA - CARTERA BASORA & ARRIAGA")
    print(f"Modo: {'🔴 PRODUCCIÓN (COMMIT ACTIVADO)' if commit else '🟡 SIMULACIÓN (DRY-RUN, NO MODIFICA BD)'}")
    print(f"Archivo CSV: {csv_path}")
    print(f"Usuario destino: {email_cliente}")
    print("=" * 70)

    if not os.path.exists(csv_path):
        print(f"❌ Error: El archivo {csv_path} no existe.")
        return

    with open(csv_path, encoding='utf-8') as f:
        rows = list(csv.DictReader(f))

    print(f"📄 Filas leídas del archivo: {len(rows)}")

    # Iniciar transacción
    with transaction.atomic():
        # 1. Obtener o crear Usuario Cliente
        user, user_created = User.objects.get_or_create(
            username=email_cliente,
            defaults={
                'email': email_cliente,
                'first_name': 'Lic. Rafael',
                'last_name': 'Basora',
            }
        )
        if user_created:
            user.set_password('Basora2026!*')
            user.save()
            print(f"👤 Creado nuevo usuario: {user.email} (Contraseña inicial: Basora2026!*)")
        else:
            print(f"👤 Usuario existente localizado: {user.email}")

        # 2. Portafolio
        portafolio = Portafolio.objects.filter(propietario=user).first()
        if not portafolio:
            portafolio = Portafolio.objects.create(
                nombre="Basora & Arriaga Gestión Inmobiliaria",
                propietario=user,
                telefono_contacto="(809) 307-8582",
                direccion_fisica="Santo Domingo, República Dominicana",
                formato_concepto_factura='RANGO_FECHAS'
            )
            print(f"📁 Creado nuevo portafolio: '{portafolio.nombre}' (ID: {portafolio.id})")
        else:
            portafolio.formato_concepto_factura = 'RANGO_FECHAS'
            portafolio.save()
            print(f"📁 Usando portafolio existente: '{portafolio.nombre}' (ID: {portafolio.id}) con formato RANGO_FECHAS")

        # 3. Suscripción activa si no tiene
        if not hasattr(user, 'suscripcion'):
            plan = PlanSaaS.objects.filter(activo=True).first()
            from datetime import timedelta
            SuscripcionCliente.objects.create(
                usuario=user,
                plan_saas=plan,
                estado='ACTIVA',
                fecha_proximo_pago=timezone.now().date() + timedelta(days=60)
            )
            print("💳 Activada suscripción SaaS para el cliente.")

        # Cache de entidades en memoria para no duplicar
        propietarios_cache = {}
        inquilinos_cache = {}

        total_propiedades_creadas = 0
        total_propietarios_creados = 0
        total_inquilinos_creados = 0
        total_contratos_creados = 0
        total_cargos_creados = 0
        total_renta_acumulada = Decimal('0.00')
        total_depositos_acumulados = Decimal('0.00')

        for idx, row in enumerate(rows, start=1):
            exp_inm = limpiar_texto(row.get('Expediente inmueble\nA-', ''))
            nombre_prop = limpiar_texto(row.get('Propietario (a)', ''))[:150]
            cedula_prop = limpiar_texto(row.get('Identificación del Propietario (a)', ''))[:50]
            celular_prop = (limpiar_telefono(row.get('Celular del Propietario (a)', '')) or 
                            limpiar_telefono(row.get('Teléfono del Propietario (a)', '')) or None)
            correo_prop = limpiar_texto(row.get('Correo electrónico del Propietario (a)', ''))
            dir_prop = limpiar_texto(row.get('Dirección Física del Propietario (a)', ''))
            banco = limpiar_texto(row.get('Banco', ''))[:100]
            tipo_cuenta = limpiar_texto(row.get('Tipo de Cuenta', ''))[:50]
            num_cuenta = limpiar_texto(row.get('Número de Cuenta', ''))[:50]

            # A. PROPIETARIO
            prop_key = cedula_prop if cedula_prop else nombre_prop.upper()
            propietario_obj = None

            if prop_key:
                if prop_key in propietarios_cache:
                    propietario_obj = propietarios_cache[prop_key]
                else:
                    # Buscar en BD o crear
                    propietario_obj = PropietarioInmueble.objects.filter(portafolio=portafolio, nombre__iexact=nombre_prop).first()
                    if not propietario_obj and cedula_prop:
                        propietario_obj = PropietarioInmueble.objects.filter(portafolio=portafolio, cedula_o_rnc=cedula_prop).first()

                    if not propietario_obj:
                        propietario_obj = PropietarioInmueble.objects.create(
                            portafolio=portafolio,
                            nombre=nombre_prop,
                            cedula_o_rnc=cedula_prop or None,
                            telefono=celular_prop or None,
                            correo=correo_prop or None,
                            direccion=dir_prop or None,
                            banco_nombre=banco or None,
                            tipo_cuenta=tipo_cuenta or None,
                            numero_cuenta=num_cuenta or None,
                            porcentaje_comision=Decimal('10.00')
                        )
                        total_propietarios_creados += 1
                    propietarios_cache[prop_key] = propietario_obj

            # B. INMUEBLE / PROPIEDAD
            alias_inm = limpiar_texto(row.get('Alias Inmueble Administrado', ''))
            dir_inm = limpiar_texto(row.get('Dirección de Inmueble Administrado', ''))
            estatus_alq = limpiar_texto(row.get('Estatus alquiler', '')).lower()
            mensualidad = parse_decimal(row.get('Mensualidad alquiler', '0'))
            deposito = parse_decimal(row.get('Status depósitos', '0'))
            
            es_alquilado = 'alquilad' in estatus_alq

            nombre_unidad = alias_inm or f"Unidad {exp_inm}"
            estado_propiedad = 'OCUPADO' if es_alquilado else 'DISPONIBLE'

            # Evitar duplicar propiedad en el mismo portafolio
            propiedad_obj = Propiedad.objects.filter(portafolio=portafolio, nombre_o_numero=nombre_unidad).first()
            if not propiedad_obj:
                propiedad_obj = Propiedad.objects.create(
                    portafolio=portafolio,
                    propietario_inmueble=propietario_obj,
                    nombre_o_numero=nombre_unidad,
                    direccion_completa=dir_inm or nombre_unidad,
                    precio_alquiler_sugerido=mensualidad,
                    estado=estado_propiedad,
                    detalles=f"Expediente Inmueble: {exp_inm}. Propietario: {nombre_prop}"
                )
                total_propiedades_creadas += 1

            total_renta_acumulada += mensualidad
            total_depositos_acumulados += deposito

            # C. INQUILINO Y CONTRATO (Solo si está alquilado y hay nombre de inquilino)
            nombre_inq = limpiar_texto(row.get('Inquilino (a)', ''))[:150]
            cedula_inq = limpiar_texto(row.get('Documento de Identidad del Inquilino (a)', ''))[:50]
            tel_inq = (limpiar_telefono(row.get('Celular Inquilino (a)', '')) or 
                       limpiar_telefono(row.get('Teléfono Inquilino (a)', '')) or "N/D")
            correo_inq = limpiar_texto(row.get('Correo Electrónico Inquilino (a)', ''))

            if es_alquilado and nombre_inq and nombre_inq.lower() not in ['desocupado', 'na', 'n/a']:
                inq_key = cedula_inq if cedula_inq else nombre_inq.upper()
                if inq_key in inquilinos_cache:
                    inquilino_obj = inquilinos_cache[inq_key]
                else:
                    inquilino_obj = Inquilino.objects.filter(creado_por=user, nombre__iexact=nombre_inq).first()
                    if not inquilino_obj and cedula_inq:
                        inquilino_obj = Inquilino.objects.filter(creado_por=user, cedula_o_pasaporte=cedula_inq).first()

                    if not inquilino_obj:
                        inquilino_obj = Inquilino.objects.create(
                            creado_por=user,
                            nombre=nombre_inq,
                            cedula_o_pasaporte=cedula_inq or None,
                            telefono=tel_inq or "N/D",
                            correo=correo_inq or None
                        )
                        total_inquilinos_creados += 1
                    inquilinos_cache[inq_key] = inquilino_obj

                # D. CONTRATO VIGENTE
                fecha_contrato = parse_fecha(row.get('Fecha del Contrato'))
                if not fecha_contrato:
                    fecha_contrato = parse_fecha(row.get('Fecha en la que se le entregó inmueble'))
                if not fecha_contrato:
                    fecha_contrato = date(2024, 1, 1)

                dia_cobro = parse_dia_pago(row.get('Día de pago'))

                fiador_nom = limpiar_texto(row.get('Fiador Solidario', ''))
                fiador_doc = limpiar_texto(row.get('Documento de Identidad del Fiador Solidario', ''))
                fiador_tel = limpiar_texto(row.get('Celular del Fiador Solidario', ''))

                texto_fiador = ""
                if fiador_nom:
                    texto_fiador = f"Garante/Fiador: {fiador_nom} (Doc: {fiador_doc}, Tel: {fiador_tel})"

                contrato_existente = Contrato.objects.filter(propiedad=propiedad_obj, activo=True).first()
                contrato_obj = contrato_existente
                if not contrato_existente:
                    contrato_obj = Contrato.objects.create(
                        propiedad=propiedad_obj,
                        inquilino=inquilino_obj,
                        fecha_inicio=fecha_contrato,
                        monto_renta=mensualidad,
                        monto_deposito=deposito,
                        dia_de_pago=dia_cobro,
                        dias_gracia=5,
                        porcentaje_mora=Decimal('10.00'),
                        custodia_deposito='ADMINISTRADORA_CUENTA',
                        detalles_custodia_deposito=f"Depósito registrado en migración: ${deposito:,.2f}",
                        texto_legal_generado=texto_fiador,
                        activo=True
                    )
                    total_contratos_creados += 1

                # E. SERVICIOS Y CARGOS ADICIONALES RECURRENTES
                servicio_txt = limpiar_texto(row.get('Servicio que paga adicional al alquiler', ''))
                servicio_monto_raw = row.get('Monto que paga servicio adicional alquiler', '')
                servicio_monto = parse_decimal(servicio_monto_raw)

                if servicio_monto > Decimal('0.00') and contrato_obj:
                    s_lower = servicio_txt.lower()
                    if 'agua' in s_lower and 'bomba' not in s_lower:
                        cat = 'AGUA'
                    elif 'mantenimiento' in s_lower and 'parqueo' not in s_lower:
                        cat = 'MANTENIMIENTO'
                    elif 'parqueo' in s_lower and 'mantenimiento' not in s_lower:
                        cat = 'PARQUEO'
                    elif 'bomba' in s_lower or 'luz' in s_lower:
                        cat = 'LUZ_BOMBA'
                    elif 'basura' in s_lower:
                        cat = 'BASURA'
                    else:
                        cat = 'OTRO'

                    cargo_existente = CargoAdicionalContrato.objects.filter(contrato=contrato_obj).first()
                    if not cargo_existente:
                        CargoAdicionalContrato.objects.create(
                            contrato=contrato_obj,
                            categoria=cat,
                            concepto_personalizado=servicio_txt if servicio_txt else 'Servicio Adicional',
                            monto=servicio_monto,
                            activo=True
                        )
                        total_cargos_creados += 1

        print("\n" + "=" * 70)
        print("📊 RESUMEN DE LA MIGRACIÓN")
        print("=" * 70)
        print(f"🏢 Total Inmuebles Procesados:        {total_propiedades_creadas}")
        print(f"👥 Total Propietarios Registrados:    {total_propietarios_creados}")
        print(f"👤 Total Inquilinos Registrados:      {total_inquilinos_creados}")
        print(f"📝 Total Contratos Activos Creados:   {total_contratos_creados}")
        print(f"⚙️  Cargos Adicionales Asignados:     {total_cargos_creados}")
        print(f"💰 Renta Mensual de la Cartera:       RD$ {total_renta_acumulada:,.2f}")
        print(f"🛡️  Depósitos de Fianza Custodiados:  RD$ {total_depositos_acumulados:,.2f}")
        print("=" * 70)

        if not commit:
            print("\n⚠️ AVISO: Ejecutado en modo SIMULACIÓN. Ningún dato fue guardado en la BD.")
            print("Para guardar los datos reales en la base de datos, ejecuta:")
            print("  python importar_cartera_basora.py --commit\n")
            # Forzar rollback en modo dry-run
            transaction.set_rollback(True)
        else:
            print("\n✅ ¡ÉXITO TOTAL! Todos los 132 apartamentos, contratos y propietarios han sido guardados.")


if __name__ == '__main__':
    commit_mode = '--commit' in sys.argv
    ejecutar_importacion(commit=commit_mode)
