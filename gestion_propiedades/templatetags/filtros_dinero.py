from django import template

register = template.Library()


@register.filter(name='dinero')
def dinero(value):
    """
    Formatea un número al estilo monetario US: $1,234,567.89
    Uso en template: {{ valor | dinero }}
    """
    try:
        return '{:,.2f}'.format(float(value))
    except (ValueError, TypeError):
        return value


@register.filter(name='telefono_whatsapp')
def telefono_whatsapp(value):
    """
    Limpia un número de teléfono para que sea compatible con WhatsApp wa.me.
    Remueve paréntesis, guiones, espacios y asegura el prefijo de país 1 si tiene 10 dígitos.
    """
    if not value:
        return ""
    digits = ''.join(filter(str.isdigit, str(value)))
    if not digits:
        return ""
    if len(digits) == 10:
        return "1" + digits
    if len(digits) == 11 and digits.startswith('1'):
        return digits
    if digits.startswith('00'):
        return digits[2:]
    return digits
