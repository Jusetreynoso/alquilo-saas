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
