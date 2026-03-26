from django.shortcuts import redirect
from django.urls import reverse
from .models import AccesoPortafolio

class SuscripcionMiddleware:
    """
    Middleware Guardián que intercepta las peticiones de usuarios logueados.
    Si su suscripción SaaS está Suspendida o Cancelada, bloquea el acceso al panel.
    Los usuarios Asistentes heredan el estado del portafolio de su administrador.
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
                '/login/',
                '/logout/',
                '/portal/',        # Portal del inquilino B2C
            ]
            
            es_exento = any(request.path.startswith(ruta) for ruta in rutas_exentas)
            if not es_exento and not request.path.startswith('/static/') and not request.path.startswith('/media/'):
                
                # --- LÓGICA RBAC: Determinar si es Asistente ---
                # Si el usuario es asistente de un portafolio, validamos la suscripción
                # del propietario del portafolio (no la del asistente, que no tiene).
                acceso = AccesoPortafolio.objects.filter(usuario=request.user, rol='ASISTENTE').select_related('portafolio__propietario').first()
                
                if acceso:
                    # Es un asistente: valida la suscripción del propietario
                    try:
                        suscripcion_dueno = acceso.portafolio.propietario.suscripcion
                        if suscripcion_dueno.estado in ['SUSPENDIDA', 'CANCELADA']:
                            return redirect('aviso_pago')
                    except Exception:
                        # Si el dueño tampoco tiene suscripción, bloqueamos
                        return redirect('aviso_pago')
                else:
                    # No es asistente: valida su propia suscripción (flujo normal)
                    try:
                        suscripcion = request.user.suscripcion
                        if suscripcion.estado in ['SUSPENDIDA', 'CANCELADA']:
                            return redirect('aviso_pago')
                    except Exception:
                        return redirect('aviso_pago')
                    
        response = self.get_response(request)
        return response
