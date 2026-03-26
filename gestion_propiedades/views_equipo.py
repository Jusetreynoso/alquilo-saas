from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.contrib.auth.models import User
from .models import Portafolio, AccesoPortafolio
from .utils_rbac import propietario_requerido

@login_required(login_url='/login/')
@propietario_requerido
def mi_equipo(request):
    portafolio = Portafolio.objects.filter(propietario=request.user).first()
    accesos = AccesoPortafolio.objects.filter(portafolio=portafolio)
    
    context = {
        'titulo_pagina': 'Mi Equipo Operacional',
        'portafolio': portafolio,
        'accesos': accesos
    }
    return render(request, 'gestion_propiedades/equipo/lista.html', context)

@login_required(login_url='/login/')
@propietario_requerido
def crear_asistente(request):
    portafolio = Portafolio.objects.filter(propietario=request.user).first()
    
    # Validar que no haya ya un asistente
    if AccesoPortafolio.objects.filter(portafolio=portafolio, rol='ASISTENTE').exists():
        messages.error(request, "Solo puedes tener un (1) asistente operativo asociado a tu portafolio.")
        return redirect('mi_equipo')

    if request.method == 'POST':
        nombre = request.POST.get('nombre')
        correo = request.POST.get('correo')
        password = request.POST.get('password')

        if User.objects.filter(email=correo).exists() or User.objects.filter(username=correo).exists():
            messages.error(request, "Ese correo ya está registrado en el ecosistema. Usa uno distinto.")
            return redirect('crear_asistente')

        try:
            with transaction.atomic():
                nuevo_user = User.objects.create_user(
                    username=correo,
                    email=correo,
                    password=password,
                    first_name=nombre
                )
                AccesoPortafolio.objects.create(
                    portafolio=portafolio,
                    usuario=nuevo_user,
                    rol='ASISTENTE'
                )
            messages.success(request, f"¡Asistente '{nombre}' vinculado con éxito! Ya puede iniciar sesión.")
            return redirect('mi_equipo')
        except Exception as e:
            messages.error(request, f"Error al procesar: {str(e)}")
            return redirect('crear_asistente')

    context = {
        'titulo_pagina': 'Invitar Nuevo Asistente',
        'portafolio': portafolio
    }
    return render(request, 'gestion_propiedades/equipo/crear.html', context)

@login_required(login_url='/login/')
@propietario_requerido
def eliminar_asistente(request, acceso_id):
    acceso = get_object_or_404(AccesoPortafolio, id=acceso_id, portafolio__propietario=request.user)
    
    # Eliminamos primero al User base para purgarlo del ecosistema
    user_purgar = acceso.usuario
    user_purgar.delete() # Esto hace on_delete=CASCADE en AccesoPortafolio
    
    messages.success(request, "Asistente revocado y eliminado permanentemente.")
    return redirect('mi_equipo')
