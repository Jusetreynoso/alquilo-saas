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
    contrato = Contrato.objects.filter(inquilino=inquilino, activo=True).select_related('propiedad').first()
    
    facturas_pendientes = []
    historial_facturas = []
    incidencias_recientes = []
    
    if contrato:
        facturas_pendientes = Factura.objects.filter(contrato=contrato, estado='PENDIENTE').order_by('fecha_vencimiento')
        historial_facturas = Factura.objects.filter(contrato=contrato).exclude(estado='PENDIENTE').order_by('-fecha_emision')[:5]
        
        from .models import MantenimientoUnidad
        incidencias_recientes = MantenimientoUnidad.objects.filter(
            propiedad=contrato.propiedad
        ).order_by('-fecha_reporte', '-id')[:4]
        
    context = {
        'inquilino': inquilino,
        'contrato': contrato,
        'facturas_pendientes': facturas_pendientes,
        'historial_facturas': historial_facturas,
        'incidencias_recientes': incidencias_recientes,
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
    contrato = Contrato.objects.filter(inquilino=inquilino, activo=True).select_related('propiedad').first()
    
    if not contrato:
        messages.warning(request, "No posees un contrato de alquiler activo en este momento para emitir reportes.")
        return redirect('portal_dashboard')
    
    if request.method == 'POST':
        from .models import MantenimientoUnidad
        titulo = request.POST.get('titulo', '').strip()
        descripcion = request.POST.get('descripcion', '').strip()
        foto = request.FILES.get('foto_averia')
        
        if not titulo or not descripcion:
            messages.error(request, "Por favor indica el título y los detalles de la avería.")
            return render(request, 'gestion_propiedades/portal/mantenimiento.html', {'contrato': contrato, 'inquilino': inquilino})
        
        texto_descripcion = f"Avería: {titulo}\n\nReportado por: {inquilino.nombre} (Tel: {inquilino.telefono})\n\nDetalles del problema:\n{descripcion}"
        
        mantenimiento = MantenimientoUnidad.objects.create(
            propiedad=contrato.propiedad,
            categoria='REPARACION',
            descripcion=texto_descripcion,
            costo=0.00,
            estado='PENDIENTE'
        )
        if foto:
            mantenimiento.factura_adjunta = foto
            mantenimiento.save()
            
        messages.success(request, "Tu reporte de incidencia ha sido enviado exitosamente al administrador de la propiedad.")
        return redirect('portal_dashboard')
        
    return render(request, 'gestion_propiedades/portal/mantenimiento.html', {'contrato': contrato, 'inquilino': inquilino})
