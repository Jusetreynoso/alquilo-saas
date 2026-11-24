import re

# Lista de dominios de correos desechables, temporales o comúnmente usados por bots de spam
DOMINIOS_DESECHABLES = {
    'immenseignite.info',
    'mailinator.com',
    'guerrillamail.com',
    'guerrillamailblock.com',
    'tempmail.com',
    'temp-mail.org',
    '10minutemail.com',
    'yopmail.com',
    'trashmail.com',
    'sharklasers.com',
    'dispostable.com',
    'getairmail.com',
    'throwawaymail.com',
    'inboxkitten.com',
    'fakemailgenerator.com',
    'burnermail.io',
    'mohmal.com',
    'crazymailing.com',
    'nada.ltd',
    'getnada.com',
    'mytemp.email',
    'zillamail.com',
}

VOCALES_REGEX = re.compile(r'[aeiouáéíóúyü]', re.IGNORECASE)
CONSONANTES_CONSECUTIVAS_REGEX = re.compile(r'[bcdfghjklmnñpqrstvwxyz]{5,}', re.IGNORECASE)


def es_correo_desechable(email: str) -> bool:
    """Verifica si el correo pertenece a un proveedor desechable o sospechoso."""
    if not email or '@' not in email:
        return True
    
    dominio = email.strip().lower().split('@')[-1]
    
    if dominio in DOMINIOS_DESECHABLES:
        return True
        
    # Bloquear dominios temporales .info o .buzz de una sola palabra con longitud atípica de bot
    partes = dominio.split('.')
    if len(partes) >= 2 and partes[-1] in ('info', 'xyz', 'top', 'buzz', 'bid'):
        nombre_dominio = partes[0]
        # Si el dominio tiene más de 12 letras sin guiones y parece generado al azar
        if len(nombre_dominio) >= 13 and not any(char.isdigit() for char in nombre_dominio):
            if not VOCALES_REGEX.search(nombre_dominio):
                return True
                
    return False


def es_nombre_plausible(texto: str) -> bool:
    """
    Verifica que el nombre o apellido introducido sea plausible para un humano
    y no una secuencia aleatoria de caracteres generada por un bot (ej: 'dvlfkmzzmw').
    """
    if not texto:
        return False
        
    limpio = texto.strip()
    if len(limpio) < 2:
        return False
        
    # Permitir apellidos muy cortos si son solo letras (ej. 'Ng', 'Li', 'Po')
    if len(limpio) <= 2 and limpio.isalpha():
        return True
        
    # Un nombre normal de más de 2 letras debe tener al menos una vocal
    if not VOCALES_REGEX.search(limpio):
        return False
        
    # No debe tener 5 o más consonantes consecutivas (anomalía de bots como 'dvlfkmzzmw')
    if CONSONANTES_CONSECUTIVAS_REGEX.search(limpio):
        return False
        
    return True


def validar_telefono_registro(telefono: str) -> tuple[bool, str]:
    """
    Valida que el teléfono tenga un formato realista y no sea un número inventado por bot.
    En el plan NANP (+1: RD, EE.UU., Canadá):
    - Códigos de área NO pueden empezar por 0 ni por 1 (ej: 019 es inválido).
    - Los dígitos centrales tampoco pueden empezar por 0 ni 1.
    """
    if not telefono:
        return False, "El número de teléfono o WhatsApp es obligatorio."
        
    digitos = re.sub(r'\D', '', telefono)
    
    if len(digitos) < 10 or len(digitos) > 15:
        return False, "Por favor introduce un número de teléfono con al menos 10 dígitos."
        
    # Rechazar números con todos los dígitos idénticos (ej. 1111111111, 0000000000)
    if len(set(digitos)) <= 1:
        return False, "El número de teléfono ingresado no parece válido."
        
    # Validación para números de 10 u 11 dígitos en zona +1 (RD y Norteamérica)
    if len(digitos) == 11 and digitos.startswith('1'):
        digitos_locales = digitos[1:]
    elif len(digitos) == 10:
        digitos_locales = digitos
    else:
        digitos_locales = None
        
    if digitos_locales:
        codigo_area = digitos_locales[:3]
        codigo_central = digitos_locales[3:6]
        
        # En NANP ningún código de área empieza con 0 o 1
        if codigo_area[0] in ('0', '1'):
            return False, f"El código de área '{codigo_area}' no es válido. En República Dominicana usa 809, 829 o 849."
            
        # Ningún código de intercambio de 3 dígitos empieza con 0 o 1
        if codigo_central[0] in ('0', '1'):
            return False, "El formato del número de teléfono ingresado no es válido."
            
    return True, ""


def validar_registro_publico(post_data: dict) -> tuple[bool, str, bool]:
    """
    Valida los datos de registro público.
    Retorna (es_valido, mensaje_error, es_bot_silencioso).
    Si es_bot_silencioso=True, el honeypot atrapó al bot y se debe simular éxito
    o rechazar sin procesar nada en la base de datos ni enviar alertas por correo.
    """
    # 1. Trampa Honeypot: Campo oculto que los humanos nunca ven ni llenan
    honeypot_valor = post_data.get('empresa_confirmacion') or post_data.get('website_url') or ''
    if honeypot_valor.strip():
        # Atrapado en el honeypot
        return False, "Registro no completado.", True
        
    first_name = post_data.get('first_name', '').strip()
    last_name = post_data.get('last_name', '').strip()
    email = post_data.get('email', '').strip()
    telefono = post_data.get('telefono', '').strip()
    nombre_portafolio = post_data.get('nombre_portafolio', '').strip()
    
    # 2. Validación de nombres humanos
    if not es_nombre_plausible(first_name):
        return False, "Por favor introduce un nombre válido.", False
        
    if not es_nombre_plausible(last_name):
        return False, "Por favor introduce un apellido válido.", False
        
    if len(nombre_portafolio) < 2:
        return False, "Por favor introduce el nombre de tu portafolio o inmobiliaria.", False
        
    # 3. Validación de correo
    if es_correo_desechable(email):
        return False, "No se permiten correos temporales o desechables. Por favor usa un correo real (Gmail, Outlook, corporativo, etc.).", False
        
    # 4. Validación de teléfono / WhatsApp
    tel_ok, tel_msg = validar_telefono_registro(telefono)
    if not tel_ok:
        return False, tel_msg, False
        
    return True, "", False
