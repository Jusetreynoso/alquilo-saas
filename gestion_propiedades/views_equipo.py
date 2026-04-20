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
    
    try:
        if request.user.suscripcion.estado != 'ACTIVA':
            messages.error(request, "Las cuentas en período de prueba o suspendidas no están habilitadas para agregar miembros al equipo corporativo.")
            return redirect('mi_equipo')
    except Exception:
        pass
    
    try:
        # Lógica VIP
        limite_gratis = 2 + request.user.suscripcion.asistentes_gratuitos_extra
        # Contar usuarios (Dueño + asistentes)
        usuarios_activos = 1 + AccesoPortafolio.objects.filter(portafolio=portafolio).count()
        excede_limite = usuarios_activos >= limite_gratis
    except Exception:
        limite_gratis = 2
        excede_limite = False

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
        'portafolio': portafolio,
        'excede_limite': excede_limite,
        'limite_gratis': limite_gratis
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

@login_required(login_url='/login/')
def cambiar_password(request, usuario_id):
    TargetUser = get_object_or_404(User, id=usuario_id)
    es_propietario = False
    
    if request.user.id != TargetUser.id:
        acceso = AccesoPortafolio.objects.filter(usuario=TargetUser, portafolio__propietario=request.user).first()
        if not acceso:
            messages.error(request, "Acción denegada. No tienes permisos para cambiar la clave de este usuario.")
            return redirect('dashboard')
        es_propietario = True
    else:
        if Portafolio.objects.filter(propietario=request.user).exists():
            es_propietario = True

    if request.method == 'POST':
        nueva_clave = request.POST.get('password')
        if nueva_clave and len(nueva_clave) >= 8:
            TargetUser.set_password(nueva_clave)
            TargetUser.save()
            
            if request.user.id == TargetUser.id:
                from django.contrib.auth import update_session_auth_hash
                update_session_auth_hash(request, TargetUser)
                messages.success(request, "Tu contraseña ha sido actualizada con éxito.")
                return redirect('dashboard')
            else:
                messages.success(request, f"La contraseña del asistente {TargetUser.first_name} ha sido actualizada.")
                return redirect('mi_equipo')
        else:
            messages.error(request, "La contraseña no es válida o es muy corta (mínimo 8 caracteres).")

    context = {
        'titulo_pagina': f'Cambiar Contraseña: {TargetUser.first_name or TargetUser.username}',
        'target_user': TargetUser,
        'es_propietario': es_propietario
    }
    return render(request, 'gestion_propiedades/equipo/cambiar_password.html', context)
