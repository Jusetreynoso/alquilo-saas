"""
Servicio reutilizable para la generación de enlaces de WhatsApp (wa.me)
y tokens firmados de recibos públicos en Alquilo.

Este módulo no depende de lógica interna de vistas y encapsula:
1. Normalización de teléfonos (soporte para República Dominicana e internacional).
2. Construcción de enlaces URL-encoded con UTF-8, saltos de línea y emojis.
3. Plantillas por defecto del sistema y renderizado seguro de variables.
4. Generación y validación de tokens criptográficos temporales para recibos (30 días).
"""

import re
import urllib.parse
from decimal import Decimal
from django.core import signing


# Prefijos telefónicos oficiales de República Dominicana (NANP)
PREFIJOS_RD = ('809', '829', '849')

# Variables permitidas en las plantillas personalizadas y del sistema
VARIABLES_PERMITIDAS = {
    'inquilino',
    'inmueble',
    'periodo',
    'monto',
    'mora',
    'saldo',
    'fecha_vencimiento',
    'agencia',
    'link_recibo',
}

# Plantillas estándar por defecto en español
PLANTILLAS_POR_DEFECTO = {
    'RECORDATORIO': (
        "Estimado/a {inquilino}:\n\n"
        "Le saludamos de {agencia}. Le informamos que el pago de su alquiler correspondiente al período {periodo} "
        "vence el {fecha_vencimiento}.\n\n"
        "Monto a pagar: RD$ {monto}\n"
        "Balance pendiente: RD$ {saldo}\n\n"
        "Le agradecemos realizar su pago a la brevedad. Si ya realizó el pago, favor enviarnos el comprobante.\n\n"
        "Ref. {inmueble}\n"
        "Quedamos a su orden."
    ),
    'MORA': (
        "Estimado/a {inquilino}:\n\n"
        "Le saludamos de {agencia}. Le informamos que el pago de su alquiler correspondiente al período {periodo} "
        "venció el {fecha_vencimiento}.\n\n"
        "Balance pendiente: RD$ {saldo}\n"
        "(incluye RD$ {mora} por cargo de mora)\n\n"
        "Le agradecemos regularizar su pago a la brevedad. Si ya realizó el pago, favor enviarnos el comprobante.\n\n"
        "Ref. {inmueble}\n"
        "Quedamos a su orden."
    ),
    'RECIBO': (
        "Estimado/a {inquilino}:\n\n"
        "Le saludamos de {agencia}. Confirmamos la recepción del pago de su alquiler correspondiente al período {periodo}.\n\n"
        "Monto abonado: RD$ {monto}\n"
        "Balance pendiente: RD$ {saldo}\n\n"
        "Puede ver y descargar su recibo oficial aquí:\n"
        "{link_recibo}\n\n"
        "Ref. {inmueble}\n"
        "¡Muchas gracias! Quedamos a su orden."
    ),
}

MESES_ES = {
    1: 'enero', 2: 'febrero', 3: 'marzo', 4: 'abril', 5: 'mayo', 6: 'junio',
    7: 'julio', 8: 'agosto', 9: 'septiembre', 10: 'octubre', 11: 'noviembre', 12: 'diciembre'
}


def formatear_fecha_es(fecha) -> str:
    """Formatea una fecha en formato natural en español (ej: 6 de octubre de 2026)."""
    if not fecha:
        return ""
    mes = MESES_ES.get(fecha.month, '')
    return f"{fecha.day} de {mes} de {fecha.year}"


def formatear_periodo_alquiler(concepto: str | None) -> str:
    """
    Convierte conceptos de facturación interna en redacción natural del período de alquiler.
    Ej:
    - 'PAGO DESDE EL 1 DE SEPTIEMBRE DEL 2026 HASTA EL 1 DE OCTUBRE DEL 2026'
      -> 'del 1 de septiembre al 1 de octubre de 2026'
    - 'Renta Octubre 2026' -> 'de octubre de 2026'
    """
    if not concepto:
        return "del mes en curso"
    s = str(concepto).strip()
    m = re.match(
        r'^PAGO DESDE (?:EL )?(.+?) DEL? (\d{4}) HASTA (?:EL )?(.+?) DEL? (\d{4})(?: \((.*?)\))?$',
        s,
        re.IGNORECASE
    )
    if m:
        f1, y1, f2, y2, extra = m.groups()
        if y1 == y2:
            base = f"del {f1.strip().lower()} al {f2.strip().lower()} de {y2}"
        else:
            base = f"del {f1.strip().lower()} de {y1} al {f2.strip().lower()} de {y2}"
        if extra:
            base += f" ({extra.capitalize()})"
        return base

    m2 = re.match(r'^(?:Renta|Alquiler)\s+(.+)$', s, re.IGNORECASE)
    if m2:
        return f"de {m2.group(1).strip()}"

    return s

SALT_RECIBO_PUBLICO = 'whatsapp-recibo-publico-v1'
DURACION_TOKEN_RECIBO_SEGUNDOS = 30 * 86400  # 30 días


def normalizar_telefono(telefono: str | None) -> str | None:
    """
    Limpia y valida un número de teléfono para la API de WhatsApp (wa.me).
    
    Reglas:
    - Deja únicamente dígitos.
    - Números de 10 dígitos que comiencen con 809, 829 o 849 (RD) se convierten a '1' + número (11 dígitos).
    - Números de 11 dígitos que comiencen con '1' y un prefijo dominicano válido se respetan.
    - Números internacionales de 11 a 15 dígitos con código de país se respetan.
    - Números que inicien con prefijo internacional '00' se limpian a su código de país.
    - Números menores de 10 dígitos, vacíos, None o que no cumplan el formato retornan None.
    """
    if telefono is None:
        return None
    
    raw = str(telefono).strip()
    if not raw:
        return None

    # Si empieza con '00', quitarlo
    if raw.startswith('00'):
        raw = raw[2:]

    digits = re.sub(r'\D', '', raw)
    if not digits:
        return None

    # Caso RD / NANP: 10 dígitos empezando con 809, 829 o 849
    if len(digits) == 10:
        if digits.startswith(PREFIJOS_RD):
            return f"1{digits}"
        return None

    # Caso RD / NANP con código de país 1: 11 dígitos
    if len(digits) == 11 and digits.startswith('1'):
        if digits[1:].startswith(PREFIJOS_RD):
            return digits
        # Otros códigos NANP válidos
        return digits

    # Caso internacional E.164: entre 11 y 15 dígitos
    if 11 <= len(digits) <= 15:
        return digits

    return None


def construir_enlace(telefono: str | None, mensaje: str | None) -> str | None:
    """
    Construye la URL 'https://wa.me/<numero>?text=<quote>' con codificación UTF-8 segura,
    respetando acentos, saltos de línea y emojis.
    Retorna None si el teléfono es inválido o el mensaje está vacío.
    """
    tel_norm = normalizar_telefono(telefono)
    if not tel_norm:
        return None

    if not mensaje:
        return None

    mensaje_limpio = str(mensaje).strip()
    if not mensaje_limpio:
        return None

    # urllib.parse.quote codifica en UTF-8 por defecto; safe='' asegura que caracteres
    # reservados como '?' '&' '#' '=' no rompan la query string de WhatsApp.
    encoded_text = urllib.parse.quote(mensaje_limpio, safe='')
    return f"https://wa.me/{tel_norm}?text={encoded_text}"


def validar_variables_plantilla(texto: str) -> tuple[bool, set[str]]:
    """
    Verifica que el texto de una plantilla solo utilice las variables permitidas.
    Retorna (es_valido, conjunto_variables_invalidas).
    """
    if not texto:
        return True, set()
    
    variables_encontradas = set(re.findall(r'\{([^{}]+)\}', texto))
    invalidas = variables_encontradas - VARIABLES_PERMITIDAS
    return len(invalidas) == 0, invalidas


def formatear_dinero(monto: Decimal | float | int | None) -> str:
    """Formatea montos monetarios en formato RD$ 1,234.56"""
    try:
        val = Decimal(str(monto or '0.00'))
        return f"{val:,.2f}"
    except Exception:
        return "0.00"


def obtener_texto_plantilla(portafolio, tipo: str) -> str:
    """
    Obtiene la plantilla personalizada activa para el tenant (Portafolio).
    Si no existe o está inactiva, retorna la plantilla por defecto del sistema.
    """
    tipo_upper = str(tipo or '').upper().strip()
    
    if portafolio and hasattr(portafolio, 'plantillas_whatsapp'):
        try:
            plantilla_custom = portafolio.plantillas_whatsapp.filter(tipo=tipo_upper, activo=True).first()
            if plantilla_custom and plantilla_custom.texto.strip():
                return plantilla_custom.texto.strip()
        except Exception:
            pass

    return PLANTILLAS_POR_DEFECTO.get(tipo_upper, PLANTILLAS_POR_DEFECTO['RECORDATORIO'])


def generar_mensaje_whatsapp(
    tipo: str,
    factura=None,
    recibo=None,
    portafolio=None,
    link_recibo: str = ""
) -> str:
    """
    Compone el texto final del mensaje de WhatsApp resolviendo las variables
    del contrato, factura, recibo y agencia de forma segura.
    """
    # Determinar portafolio si no se pasa explícitamente
    if not portafolio:
        if factura and hasattr(factura, 'contrato') and factura.contrato:
            portafolio = factura.contrato.propiedad.portafolio
        elif recibo and hasattr(recibo, 'factura') and recibo.factura and recibo.factura.contrato:
            portafolio = recibo.factura.contrato.propiedad.portafolio

    # Si se pasó recibo pero no factura, inferir la factura
    if recibo and not factura and hasattr(recibo, 'factura'):
        factura = recibo.factura

    contrato = factura.contrato if factura and hasattr(factura, 'contrato') else None
    inquilino = contrato.inquilino if contrato and hasattr(contrato, 'inquilino') else None
    propiedad = contrato.propiedad if contrato and hasattr(contrato, 'propiedad') else None

    # Extraer valores seguros
    nombre_inquilino = inquilino.nombre.strip() if inquilino and inquilino.nombre else "Estimado/a Inquilino/a"
    nombre_inmueble = propiedad.nombre_o_numero if propiedad else "su inmueble"
    nombre_agencia = portafolio.nombre if portafolio and portafolio.nombre else "la Administración"
    
    concepto_periodo = ""
    if factura and getattr(factura, 'concepto', None):
        concepto_periodo = formatear_periodo_alquiler(factura.concepto)
    elif contrato:
        concepto_periodo = f"de {propiedad.nombre_o_numero}" if propiedad else "del mes en curso"

    # Montos
    if recibo:
        monto_str = formatear_dinero(getattr(recibo, 'monto_pagado', Decimal('0.00')))
    elif factura:
        monto_str = formatear_dinero(getattr(factura, 'monto_base', Decimal('0.00')))
    else:
        monto_str = "0.00"

    total_mora_val = getattr(factura, 'total_mora', Decimal('0.00')) if factura else Decimal('0.00')
    mora_str = formatear_dinero(total_mora_val)
    saldo_str = formatear_dinero(getattr(factura, 'saldo_pendiente', Decimal('0.00'))) if factura else "0.00"

    fecha_venc_str = ""
    if factura and getattr(factura, 'fecha_vencimiento', None):
        fecha_venc_str = formatear_fecha_es(factura.fecha_vencimiento)

    contexto = {
        'inquilino': nombre_inquilino,
        'inmueble': nombre_inmueble,
        'periodo': concepto_periodo,
        'monto': monto_str,
        'mora': mora_str,
        'saldo': saldo_str,
        'fecha_vencimiento': fecha_venc_str,
        'agencia': nombre_agencia,
        'link_recibo': link_recibo or "",
    }

    plantilla = obtener_texto_plantilla(portafolio, tipo)

    # Si la mora acumulada es 0.00, omitir la línea de mora para mantener el mensaje limpio
    if total_mora_val <= Decimal('0.00'):
        plantilla = plantilla.replace("\n(incluye RD$ {mora} por cargo de mora)", "")
        plantilla = plantilla.replace("(incluye RD$ {mora} por cargo de mora)", "")

    # Reemplazo seguro de variables (evita excepciones si falta alguna clave no esperada)
    for k, v in contexto.items():
        plantilla = plantilla.replace(f"{{{k}}}", str(v))

    return plantilla


def generar_token_recibo(recibo_id: int | str) -> str:
    """
    Genera un token firmado criptográficamente que codifica el ID del recibo.
    Inmune a alteración y no predecible.
    """
    signer = signing.TimestampSigner(salt=SALT_RECIBO_PUBLICO)
    return signer.sign(str(recibo_id))


def validar_token_recibo(token: str, max_age_seconds: int = DURACION_TOKEN_RECIBO_SEGUNDOS) -> int | None:
    """
    Valida un token firmado de recibo y retorna el recibo_id (int).
    Si el token es inválido, manipulado o expiró (> 30 días), retorna None.
    """
    if not token:
        return None
    signer = signing.TimestampSigner(salt=SALT_RECIBO_PUBLICO)
    try:
        raw_id = signer.unsign(token, max_age=max_age_seconds)
        return int(raw_id)
    except (signing.BadSignature, signing.SignatureExpired, ValueError):
        return None
