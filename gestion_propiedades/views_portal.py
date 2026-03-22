from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from functools import wraps
from .models import Inquilino, Contrato, Factura

def inquilino_required(view_func):
    """Decorador para asegurar que solo los inquilinos logueados entren al portal"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if 'inquilino_id' not in request.session:
            return redirect('portal_login')
        return view_func(request, *args, **kwargs)
    return _wrapped_view

def portal_login(request):
    if 'inquilino_id' in request.session:
        return redirect('portal_dashboard')

    if request.method == 'POST':
        correo = request.POST.get('correo')
        cedula = request.POST.get('cedula')
        
        if not correo or not cedula:
            messages.error(request, "Ambos campos son obligatorios.")
            return render(request, 'gestion_propiedades/portal/login.html')
            
        inquilino = Inquilino.objects.filter(correo=correo.strip(), cedula_o_pasaporte=cedula.strip()).first()
        if inquilino:
            request.session['inquilino_id'] = inquilino.id
            return redirect('portal_dashboard')
        else:
            messages.error(request, "No encontramos un registro con ese Correo y Documento de Identidad.")
            
    return render(request, 'gestion_propiedades/portal/login.html')

@inquilino_required
def portal_dashboard(request):
    inquilino_id = request.session.get('inquilino_id')
    inquilino = get_object_or_404(Inquilino, id=inquilino_id)
    contrato = Contrato.objects.filter(inquilino=inquilino, activo=True).first()
    
    facturas_pendientes = []
    historial_facturas = []
    if contrato:
        facturas_pendientes = Factura.objects.filter(contrato=contrato, estado='PENDIENTE').order_by('fecha_vencimiento')
        historial_facturas = Factura.objects.filter(contrato=contrato).exclude(estado='PENDIENTE').order_by('-fecha_emision')[:5]
        
    context = {
        'inquilino': inquilino,
        'contrato': contrato,
        'facturas_pendientes': facturas_pendientes,
        'historial_facturas': historial_facturas
    }
    return render(request, 'gestion_propiedades/portal/dashboard.html', context)

@inquilino_required
def portal_logout(request):
    if 'inquilino_id' in request.session:
        del request.session['inquilino_id']
    return redirect('portal_login')

@inquilino_required
def portal_mantenimiento(request):
    inquilino_id = request.session.get('inquilino_id')
    inquilino = get_object_or_404(Inquilino, id=inquilino_id)
    contrato = Contrato.objects.filter(inquilino=inquilino, activo=True).first()
    
    if request.method == 'POST' and contrato:
        # Importación diferida para evitar ciclos
        from .models import MantenimientoGlobal
        titulo = request.POST.get('titulo')
        descripcion = request.POST.get('descripcion')
        
        MantenimientoGlobal.objects.create(
            propiedad=contrato.propiedad,
            titulo=f"[Portal Inquilino] {titulo}",
            descripcion=f"Reportado por: {inquilino.nombre} - Tel: {inquilino.telefono}\n\nDetalles del problema:\n{descripcion}",
            estado='PENDIENTE',
            prioridad='MEDIA'
        )
        messages.success(request, "Tu incidencia ha sido enviada exitosamente al administrador de la propiedad.")
        return redirect('portal_dashboard')
        
    return render(request, 'gestion_propiedades/portal/mantenimiento.html', {'contrato': contrato})
