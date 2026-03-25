from django.shortcuts import redirect
from django.contrib import messages
from functools import wraps
from .models import Portafolio

def propietario_requerido(view_func):
    """
    Escudo B2B: Solo los usuarios que sean 'Propietarios' de al menos un portafolio 
    pueden acceder a esta vista. Bloquea el paso a los 'Asistentes'.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not Portafolio.objects.filter(propietario=request.user).exists():
            messages.error(request, "Acción denegada. Solo el Administrador de la cuenta puede acceder a esta área.")
            return redirect('dashboard')
        return view_func(request, *args, **kwargs)
    return _wrapped_view
