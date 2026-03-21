def avisos_globales(request):
    """
    Context Processor que inyecta los `AvisoSistema` activos en absolutamente
    todas las vistas de la aplicación para renderizarlos en el header.
    """
    from .models import AvisoSistema
    avisos = AvisoSistema.objects.filter(activo=True).order_by('-fecha_creacion')
    return {'avisos_superiores': avisos}
