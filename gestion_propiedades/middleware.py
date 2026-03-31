from django.shortcuts import redirect
from django.urls import reverse
from .models import AccesoPortafolio
import threading

_thread_local = threading.local()


class CurrentUserMiddleware:
    """Inyecta el usuario logueado en un thread-local para que los signals puedan acceder a él."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _thread_local.usuario = getattr(request, 'user', None)
        response = self.get_response(request)
        return response


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

class NoCacheMiddleware:
    """
    Escudo de Seguridad Zero-Trust:
    Si un usuario ha iniciado sesión, este guardián le inyecta cabeceras a la respuesta HTTP
    ordenándole a Firefox, Chrome y Safari no guardar 'fantasmas' de estas páginas en su caché.
    Esto previene que al darle 'Atrás' luego de cerrar sesión se expongan datos financieros privados.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        
        # Solo aplicar el candado a rutas protegidas (usualmente las que requieren login)
        # Eximimos las rutas de archivos estáticos o media para no ralentizar el servidor
        if request.user.is_authenticated and not request.path.startswith('/static/') and not request.path.startswith('/media/'):
            response['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
            response['Pragma'] = 'no-cache'
            response['Expires'] = '0'
            
        return response
