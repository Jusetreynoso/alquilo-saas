def avisos_globales(request):
    """
    Context Processor que inyecta los `AvisoSistema` activos en absolutamente
    todas las vistas de la aplicación para renderizarlos en el header, y las
    alertas de incidencias / mantenimientos pendientes para los administradores y asistentes.
    """
    from .models import AvisoSistema, MantenimientoUnidad, Portafolio
    from django.db.models import Q

    avisos = AvisoSistema.objects.filter(activo=True).order_by('-fecha_creacion')
    context = {
        'avisos_superiores': avisos,
        'mantenimientos_pendientes_count': 0,
    }

    if request.user.is_authenticated and not request.path.startswith('/portal/'):
        if request.user.is_superuser:
            pendientes_qs = MantenimientoUnidad.objects.filter(estado='PENDIENTE')
        else:
            portafolios = Portafolio.objects.filter(
                Q(propietario=request.user) | Q(accesos__usuario=request.user)
            ).distinct()
            pendientes_qs = MantenimientoUnidad.objects.filter(
                propiedad__portafolio__in=portafolios,
                estado='PENDIENTE'
            )
        context['mantenimientos_pendientes_count'] = pendientes_qs.count()

    return context

