from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import PlantillaContrato, Portafolio

@login_required
def lista_plantillas(request):
    # Obtener el portafolio del usuario (asumiendo que el dueño solo maneja 1 o que agarra el primero)
    # Si es asistente, quizas no deberia editar plantillas, pero lo limitaremos a dueño por ahora.
    if request.user.portafolios.exists():
        portafolio = request.user.portafolios.first()
        plantillas = PlantillaContrato.objects.filter(portafolio=portafolio)
    else:
        # Modo asistente, no deberia estar aquí pero por seguridad
        portafolio = None
        plantillas = []

    plantillas_sistema = PlantillaContrato.objects.filter(es_predeterminada=True)

    context = {
        'plantillas': plantillas,
        'plantillas_sistema': plantillas_sistema,
    }
    return render(request, 'gestion_propiedades/lista_plantillas.html', context)

@login_required
def editar_plantilla(request, plantilla_id=None):
    is_superuser = request.user.is_superuser
    if not request.user.portafolios.exists() and not is_superuser:
        messages.error(request, "Solo los dueños de portafolio pueden editar plantillas.")
        return redirect('dashboard')
        
    portafolio = request.user.portafolios.first() if request.user.portafolios.exists() else None
    
    if plantilla_id:
        plantilla = get_object_or_404(PlantillaContrato, id=plantilla_id)
        if plantilla.es_predeterminada:
            if not is_superuser:
                # Usuario normal: clonar
                plantilla.pk = None
                plantilla.es_predeterminada = False
                plantilla.portafolio = portafolio
                plantilla.titulo = plantilla.titulo + " (Copia)"
                plantilla.save()
                messages.success(request, "Se ha creado una copia de la plantilla del sistema para que puedas editarla.")
                return redirect('editar_plantilla', plantilla_id=plantilla.id)
            # Superuser la edita directamente
        elif plantilla.portafolio != portafolio and not is_superuser:
            messages.error(request, "No tienes permiso para editar esta plantilla.")
            return redirect('lista_plantillas')
    else:
        plantilla = None

    if request.method == 'POST':
        titulo = request.POST.get('titulo')
        contenido = request.POST.get('contenido')
        
        if not plantilla:
            plantilla = PlantillaContrato()
            if is_superuser and request.GET.get('sistema') == '1':
                plantilla.es_predeterminada = True
            else:
                plantilla.portafolio = portafolio
            
        plantilla.titulo = titulo
        plantilla.contenido = contenido
        plantilla.save()
        
        messages.success(request, "Plantilla guardada correctamente.")
        return redirect('lista_plantillas')

    return render(request, 'gestion_propiedades/editar_plantilla.html', {'plantilla': plantilla})

@login_required
def eliminar_plantilla(request, plantilla_id):
    plantilla = get_object_or_404(PlantillaContrato, id=plantilla_id)
    if (plantilla.portafolio == request.user.portafolios.first() and not plantilla.es_predeterminada) or request.user.is_superuser:
        plantilla.delete()
        messages.success(request, "Plantilla eliminada.")
    else:
        messages.error(request, "No puedes eliminar esta plantilla.")
    return redirect('lista_plantillas')
