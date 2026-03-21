from django.shortcuts import redirect
from django.urls import reverse

class SuscripcionMiddleware:
    """
    Middleware Guardián que intercepta las peticiones de usuarios logueados.
    Si su suscripción SaaS está Suspendida o Cancelada, bloquea el acceso al panel.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and not request.user.is_superuser:
            # Rutas que no deben bloquearse para evitar "Redirect Loops" infinitos
            rutas_exentas = [
                reverse('aviso_pago'),
                '/admin/',         # Permitir que entren al admin si tienen staff status
                '/solicitud/',     # Vistas públicas de solicitudes
            ]
            
            es_exento = any(request.path.startswith(ruta) for ruta in rutas_exentas)
            # Tampoco bloqueamos recursos estáticos
            if not es_exento and not request.path.startswith('/static/') and not request.path.startswith('/media/'):
                try:
                    suscripcion = request.user.suscripcion
                    if suscripcion.estado in ['SUSPENDIDA', 'CANCELADA']:
                        return redirect('aviso_pago')
                except Exception:
                    # Si el usuario NO tiene un registro de SuscripcionCliente en BD, 
                    # asumimos configuración pendiente o bloqueo por seguridad
                    return redirect('aviso_pago')
                    
        response = self.get_response(request)
        return response
