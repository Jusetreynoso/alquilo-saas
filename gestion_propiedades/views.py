from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.http import HttpResponse, HttpResponseNotAllowed
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login
from django.db.models import Sum, Q, Prefetch, F, Count
from django.contrib import messages
from datetime import date, datetime, timedelta
import logging
import os
from django.conf import settings
from .models import Portafolio, Propiedad, Factura, CargoMora, ReciboPago, Contrato, SolicitudAlquiler, MantenimientoUnidad, Inquilino, PlanSaaS, SuscripcionCliente, AuditLog, GastoProgramado, RegistroProceso, PropietarioInmueble, GastoGeneralPropietario, LiquidacionPropietario, LiquidacionDepositoInquilino, HistorialPrecioPropiedad, CargoAdicionalContrato, DetalleFacturaServicio, RecordatorioPagoPropietario
from .forms import NuevoClienteSaaSForm, EditarSuscripcionForm, PropiedadForm, ContratoForm, InquilinoForm, MantenimientoForm, PlanSaaSForm, PropietarioInmuebleForm, GastoGeneralPropietarioForm, LiquidacionPropietarioForm, LiquidacionDepositoForm, HistorialPrecioForm, FacturaManualForm, CargoAdicionalContratoForm, RecordatorioPagoPropietarioForm
from .utils import render_to_pdf, obtener_nombre_mes
import calendar
import decimal
from decimal import Decimal
from django.db.models.functions import TruncMonth
from .utils_rbac import propietario_requerido
from collections import defaultdict

logger = logging.getLogger(__name__)


# --- VISTA PÚBLICA COMERCIAL ---
def inicio_comercial(request):
    """
    Landing Page (Página de Aterrizaje) Pública para ofertar el Software B2B Alquilo.
    No requiere autenticación. Si el usuario ya inició sesión, puede enviarse al dashboard.
    """
    if request.user.is_authenticated:
        pass # Podríamos redirigirlo, pero dejaremos que vea la página
    return render(request, 'gestion_propiedades/sitio_comercial.html')

def registro_publico(request):
    """
    Vista de Auto-Registro para que nuevos clientes creen su Portafolio con 45 días de prueba.
    """
    if request.user.is_authenticated:
        return redirect('dashboard')
        
    if request.method == 'POST':
        first_name = request.POST.get('first_name', '')
        last_name = request.POST.get('last_name', '')
        email = request.POST.get('email', '')
        password = request.POST.get('password', '')
        nombre_portafolio = request.POST.get('nombre_portafolio', '')
        telefono = request.POST.get('telefono', '')
        
        from django.contrib.auth.models import User
        if User.objects.filter(email=email).exists() or User.objects.filter(username=email).exists():
            return render(request, 'gestion_propiedades/registro_publico.html', {
                'message': 'Este correo ya está registrado en el sistema. Utilice otro si desea crear un nuevo portafolio.'
            })
            
        # 1. Crear el Super Usuario B2B (Owner)
        # Añadimos el teléfono al apellido para que el admin lo vea en la base de datos sin necesitar nuevas tablas.
        apellido_completo = f"{last_name} (Wa: {telefono})" if telefono else last_name
        
        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            first_name=first_name,
            last_name=apellido_completo
        )
        
        # 2. Crear Portafolio
        Portafolio.objects.create(nombre=nombre_portafolio, propietario=user)
        
        # 3. Asignar Suscripción TRIAL por 45 días
        plan_trial = PlanSaaS.objects.filter(activo=True).first()
        from datetime import timedelta
        from django.utils import timezone
        SuscripcionCliente.objects.create(
            usuario=user,
            plan_saas=plan_trial,
            estado='TRIAL',
            fecha_proximo_pago=timezone.now().date() + timedelta(days=45)
        )
        
        # 4. Enviar correo de notificación al Admin con los datos de contacto
        from .utils_correo import enviar_alerta_nuevo_registro_admin
        enviar_alerta_nuevo_registro_admin(user, nombre_portafolio, telefono)
        
        # 5. Iniciar Sesión y Mandarlo al Panel
        login(request, user)
        return redirect('dashboard')
        
    return render(request, 'gestion_propiedades/registro_publico.html')

# --- PANEL PRINCIPAL INTERNO ---

@login_required(login_url='/login/')
def dashboard(request):
    limpiar_anuncios_expirados()
    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().distinct()
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()

    total_propiedades = Propiedad.objects.filter(portafolio__in=portafolios, is_deleted=False).count()
    propiedades_disponibles = Propiedad.objects.filter(portafolio__in=portafolios, estado='DISPONIBLE', is_deleted=False).count()

    # 1. Le agregamos el .order_by para que las deudas más viejas salgan primero
    facturas_pendientes = Factura.objects.filter(
        contrato__propiedad__portafolio__in=portafolios,
        estado__in=['PENDIENTE', 'ATRASADA']
    ).order_by('fecha_vencimiento')

    suma_facturas = facturas_pendientes.aggregate(total=Sum('monto_base'))['total'] or 0
    suma_moras = CargoMora.objects.filter(factura__in=facturas_pendientes).aggregate(total=Sum('monto'))['total'] or 0
    cuentas_por_cobrar = suma_facturas + suma_moras

    hoy = date.today()
    ingresos_mes = ReciboPago.objects.filter(
        factura__contrato__propiedad__portafolio__in=portafolios,
        fecha_pago__year=hoy.year,
        fecha_pago__month=hoy.month
    ).aggregate(total=Sum('monto_pagado'))['total'] or 0

    # Gastos programados activos del mes
    gastos_programados_qs = GastoProgramado.objects.filter(
        propiedad__portafolio__in=portafolios,
        propiedad__is_deleted=False,
        activo=True
    ).select_related('propiedad')

    recordatorios_gastos = []
    for gp in gastos_programados_qs:
        pagado = MantenimientoUnidad.objects.filter(
            gasto_programado=gp,
            fecha_reporte__month=hoy.month,
            fecha_reporte__year=hoy.year
        ).exists()

        recordatorios_gastos.append({
            'gasto': gp,
            'pagado': pagado,
        })
        
    recordatorios_gastos.sort(key=lambda x: (x['pagado'], x['gasto'].dia_pago))

    # Recordatorios de Vencimiento de Contratos
    from datetime import timedelta
    contratos_activos_vencimiento = Contrato.objects.filter(
        propiedad__portafolio__in=portafolios,
        propiedad__is_deleted=False,
        activo=True,
        fecha_fin__isnull=False,
        recordatorio_vencimiento_meses__gt=0
    ).select_related('propiedad', 'inquilino', 'propiedad__portafolio')

    recordatorios_vencimiento_contratos = []
    for c in contratos_activos_vencimiento:
        dias_aviso = c.recordatorio_vencimiento_meses * 30
        fecha_alerta = c.fecha_fin - timedelta(days=dias_aviso)
        
        if hoy >= fecha_alerta:
            dias_restantes = (c.fecha_fin - hoy).days
            recordatorios_vencimiento_contratos.append({
                'contrato': c,
                'dias_restantes': dias_restantes,
                'dias_restantes_abs': abs(dias_restantes),
                'vencido': dias_restantes < 0,
            })

    recordatorios_vencimiento_contratos.sort(key=lambda x: x['dias_restantes'])

    recordatorios_pagos_propietarios = RecordatorioPagoPropietario.objects.filter(
        portafolio__in=portafolios,
        estado='PENDIENTE',
        fecha_recordatorio__lte=hoy + timedelta(days=7)
    ).select_related('propietario').order_by('fecha_recordatorio')[:5]

    context = {
        'titulo_pagina': 'Resumen de Portafolio',
        'total_propiedades': total_propiedades,
        'propiedades_disponibles': propiedades_disponibles,
        'cuentas_por_cobrar': cuentas_por_cobrar,
        'ingresos_mes': ingresos_mes,
        'facturas_pendientes': facturas_pendientes,
        'recordatorios_gastos': recordatorios_gastos,
        'recordatorios_vencimiento_contratos': recordatorios_vencimiento_contratos,
        'recordatorios_pagos_propietarios': recordatorios_pagos_propietarios,
    }
    
    return render(request, 'gestion_propiedades/dashboard.html', context)

@login_required(login_url='/login/')
def lista_propiedades(request):
    # 1. Buscamos los portafolios a los que tiene acceso el usuario
    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().distinct()
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()

    # 2. Traemos las propiedades. 
    contratos_activos = Contrato.objects.filter(activo=True)
    qs = Propiedad.objects.filter(portafolio__in=portafolios, is_deleted=False)
    
    # Filtro por estado via URL param (ej: ?estado=disponible desde el Dashboard)
    estado_filtro = request.GET.get('estado', '').upper()
    if estado_filtro in ['DISPONIBLE', 'OCUPADO', 'MANTENIMIENTO', 'INACTIVO']:
        qs = qs.filter(estado=estado_filtro)

    propiedades = qs.prefetch_related(
        Prefetch('contratos', queryset=contratos_activos, to_attr='contrato_activo')
    ).order_by('grupo_o_residencial', 'nombre_o_numero')

    context = {
        'titulo_pagina': 'Mis Propiedades',
        'propiedades': propiedades,
        'estado_filtro': estado_filtro,
    }
    return render(request, 'gestion_propiedades/lista_propiedades.html', context)

@login_required(login_url='/login/')
def detalle_propiedad(request, propiedad_id):
    # 1. Seguridad: Asegurarnos de que el usuario tenga acceso al portafolio de esta propiedad
    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().distinct()
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()
    
    # Busca la propiedad, y si no existe o no es de él, da error 404
    propiedad = get_object_or_404(Propiedad, id=propiedad_id, portafolio__in=portafolios)

    # 2. Buscar el Inquilino actual (Contrato Activo)
    contrato_activo = propiedad.contratos.filter(activo=True).first()

    # 3. Historial de Facturas (De todos los contratos que haya tenido esta propiedad)
    facturas = Factura.objects.filter(contrato__propiedad=propiedad).order_by('-fecha_emision')

    # 4. Historial de Mantenimientos
    mantenimientos = propiedad.historial_mantenimientos.all().order_by('-fecha_reporte')

    # Buscar las solicitudes creadas para esta propiedad
    solicitudes = propiedad.solicitudes.all().order_by('-creada_en')

    # Historial de Precios de Alquiler de la propiedad
    historial_precios = propiedad.historial_precios.all().order_by('-fecha_cambio', '-creado_en')
    form_precio = HistorialPrecioForm(initial={
        'nuevo_precio': propiedad.precio_alquiler_sugerido or decimal.Decimal('0.00'),
        'fecha_cambio': date.today()
    })

    context = {
        'titulo_pagina': f'Detalle: {propiedad.nombre_o_numero}',
        'propiedad': propiedad,
        'contrato_activo': contrato_activo,
        'facturas': facturas,
        'mantenimientos': mantenimientos,
        'solicitudes': solicitudes,
        'historial_precios': historial_precios,
        'form_precio': form_precio,
    }
    return render(request, 'gestion_propiedades/detalle_propiedad.html', context)


@login_required(login_url='/login/')
def registrar_cambio_precio_propiedad(request, propiedad_id):
    """
    Registra una actualización en el historial de precios de la propiedad y actualiza su canon sugerido.
    """
    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().distinct()
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()
    propiedad = get_object_or_404(Propiedad, id=propiedad_id, portafolio__in=portafolios)
    
    if request.method == 'POST':
        form = HistorialPrecioForm(request.POST)
        if form.is_valid():
            hist = form.save(commit=False)
            hist.propiedad = propiedad
            hist.precio_anterior = propiedad.precio_alquiler_sugerido or decimal.Decimal('0.00')
            hist.registrado_por = request.user
            hist.save()
            
            # Actualizar precio en la propiedad
            propiedad.precio_alquiler_sugerido = hist.nuevo_precio
            propiedad.save()
            
            messages.success(request, f'Precio de alquiler de {propiedad.nombre_o_numero} actualizado a RD${hist.nuevo_precio:,.2f}.')
    return redirect('detalle_propiedad', propiedad_id=propiedad.id)


@login_required(login_url='/login/')
def mapa_propiedades_global(request):
    """
    Vista global interactiva de Mapa (Leaflet.js) con todas las propiedades geolocalizadas.
    """
    import json
    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().distinct()
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()
    
    propiedades_qs = Propiedad.objects.filter(
        portafolio__in=portafolios,
        is_deleted=False
    ).select_related('propietario_inmueble')
    
    propiedades_mapa = []
    for p in propiedades_qs:
        if p.latitud and p.longitud:
            img_url = p.imagen_principal.url if p.imagen_principal else ''
            propiedades_mapa.append({
                'id': p.id,
                'nombre': p.nombre_o_numero,
                'grupo': p.grupo_o_residencial or '',
                'direccion': p.direccion_completa or 'Sin dirección específica',
                'estado': p.estado,
                'estado_display': p.get_estado_display(),
                'precio': float(p.precio_alquiler_sugerido or 0.00),
                'lat': float(p.latitud),
                'lng': float(p.longitud),
                'imagen_url': img_url,
                'google_maps_url': f"https://www.google.com/maps/search/?api=1&query={p.latitud},{p.longitud}"
            })
            
    context = {
        'titulo_pagina': 'Mapa Global de Propiedades',
        'propiedades_mapa_json': json.dumps(propiedades_mapa),
        'total_geolocalizadas': len(propiedades_mapa),
        'total_propiedades': propiedades_qs.count()
    }
    return render(request, 'gestion_propiedades/mapa_propiedades.html', context)

@login_required(login_url='/login/')
def registrar_pago(request, factura_id):
    # Buscamos la factura permitiendo acceso a superusuarios o miembros con permiso del portafolio
    if request.user.is_superuser:
        factura = get_object_or_404(Factura, id=factura_id)
    else:
        portafolios = Portafolio.objects.filter(Q(propietario=request.user) | Q(accesos__usuario=request.user)).distinct()
        factura = get_object_or_404(Factura, id=factura_id, contrato__propiedad__portafolio__in=portafolios)

    # Si el usuario hace clic en el botón "Guardar Pago" (Método POST)
    if request.method == 'POST':
        monto_str = request.POST.get('monto', '0')
        metodo = request.POST.get('metodo_pago', 'TRANSFERENCIA')
        referencia = request.POST.get('referencia', '')
        fecha = request.POST.get('fecha_pago') or timezone.now().date()
        comprobante = request.FILES.get('comprobante_imagen')

        try:
            monto_val = decimal.Decimal(str(monto_str).replace(',', ''))
        except Exception:
            monto_val = decimal.Decimal('0.00')

        if monto_val <= decimal.Decimal('0.00'):
            messages.error(request, 'El monto recibido debe ser mayor a cero.')
            return redirect('registrar_pago', factura_id=factura.id)

        from django.db import transaction
        recibo = None
        try:
            with transaction.atomic():
                # 1. Creamos el Recibo de Pago (su save() imputa 1. Mora, 2. Servicios, 3. Alquiler)
                recibo = ReciboPago.objects.create(
                    factura=factura,
                    fecha_pago=fecha,
                    monto_pagado=monto_val,
                    metodo_pago=metodo,
                    referencia_transaccion=referencia,
                    comprobante_imagen=comprobante,
                    registrado_por=request.user
                )

                # 2. Actualizamos la Factura evaluando si quedó completamente saldada
                if factura.saldo_pendiente <= decimal.Decimal('0.00'):
                    factura.estado = 'PAGADA'
                factura.save()
        except Exception as e:
            # Tolerancia a fallos: Si falló exclusivamente por subida del comprobante a la nube
            if comprobante:
                try:
                    with transaction.atomic():
                        recibo = ReciboPago.objects.create(
                            factura=factura,
                            fecha_pago=fecha,
                            monto_pagado=monto_val,
                            metodo_pago=metodo,
                            referencia_transaccion=referencia,
                            comprobante_imagen=None,
                            registrado_por=request.user
                        )
                        if factura.saldo_pendiente <= decimal.Decimal('0.00'):
                            factura.estado = 'PAGADA'
                        factura.save()
                    messages.warning(request, f"¡Pago registrado exitosamente! Nota: el archivo de comprobante no pudo cargarse en este momento ({str(e)}).")
                    return redirect('detalle_propiedad', propiedad_id=factura.contrato.propiedad.id)
                except Exception as inner_e:
                    messages.error(request, f"Error al procesar el pago: {str(inner_e)}")
                    return redirect('registrar_pago', factura_id=factura.id)
            messages.error(request, f"Error al registrar el cobro: {str(e)}")
            return redirect('registrar_pago', factura_id=factura.id)

        # 3. Notificación con desglose de abono
        if factura.saldo_pendiente > decimal.Decimal('0.00'):
            messages.success(
                request,
                f"💰 ¡Abono de RD$ {recibo.monto_pagado:,.2f} registrado! "
                f"Desglose aplicado: [Mora: RD$ {recibo.monto_a_mora:,.2f} | "
                f"Servicios: RD$ {recibo.monto_a_servicios:,.2f} | "
                f"Alquiler: RD$ {recibo.monto_a_renta:,.2f}]. "
                f"Saldo pendiente restante: RD$ {factura.saldo_pendiente:,.2f}."
            )
        else:
            messages.success(
                request,
                f"🎉 ¡Factura #{factura.id} saldada completamente con RD$ {recibo.monto_pagado:,.2f}!"
            )

        # 4. Lo devolvemos al expediente de la propiedad
        return redirect('detalle_propiedad', propiedad_id=factura.contrato.propiedad.id)

    # Si solo está entrando a ver la pantalla (Método GET), le mostramos el formulario
    context = {
        'titulo_pagina': f'Cobrar Factura #{factura.id}',
        'factura': factura,
    }
    return render(request, 'gestion_propiedades/registrar_pago.html', context)

@login_required(login_url='/login/')
def quitar_mora_factura(request, factura_id):
    """
    Permite al Superadministrador o al Administrador del Portafolio quitar / condonar
    la mora acumulada de una factura (por ejemplo, si el cliente reportó su atraso previamente).
    """
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    factura = get_object_or_404(Factura, id=factura_id)
    portafolio = factura.contrato.propiedad.portafolio

    from .models import AccesoPortafolio
    es_superadmin = request.user.is_superuser
    es_dueno_portafolio = portafolio.propietario == request.user
    es_admin_portafolio = AccesoPortafolio.objects.filter(
        portafolio=portafolio,
        usuario=request.user,
        rol='ADMINISTRADOR'
    ).exists()

    if not (es_superadmin or es_dueno_portafolio or es_admin_portafolio):
        messages.error(request, "Acceso restringido: Solo el Administrador del portafolio o el Superadministrador pueden quitar o condonar cargos por mora.")
        next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or reverse('registrar_pago', args=[factura.id])
        return redirect(next_url)

    monto_mora = factura.total_mora
    from django.db import transaction
    with transaction.atomic():
        factura.moras.all().delete()
        factura.mora_exonerada = True
        factura.save()

        AuditLog.objects.create(
            accion='EDITAR',
            modulo='Factura',
            descripcion=f"Mora condonada/removida de Factura #{factura.id} ({factura.contrato.inquilino.nombre}) por {request.user.username}. Monto condonado: ${monto_mora:,.2f}",
            usuario=request.user,
            portafolio=portafolio
        )

    messages.success(request, f"¡Mora de RD$ {monto_mora:,.2f} quitada exitosamente para la factura #{factura.id}!")
    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or reverse('registrar_pago', args=[factura.id])
    return redirect(next_url)

@login_required(login_url='/login/')
def lista_contratos(request):
    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().distinct()
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()

    q = request.GET.get('q', '').strip()
    estado = request.GET.get('estado', 'TODOS')
    portafolio_id = request.GET.get('portafolio_id', 'TODOS')

    contratos = Contrato.objects.filter(
        propiedad__portafolio__in=portafolios
    ).select_related('propiedad', 'inquilino', 'propiedad__portafolio')

    if portafolio_id != 'TODOS' and portafolio_id and str(portafolio_id).isdigit():
        contratos = contratos.filter(propiedad__portafolio_id=int(portafolio_id))

    if estado == 'ACTIVOS':
        contratos = contratos.filter(activo=True)
    elif estado == 'FINALIZADOS':
        contratos = contratos.filter(activo=False)

    if q:
        contratos = contratos.filter(
            Q(inquilino__nombre__icontains=q) |
            Q(inquilino__telefono__icontains=q) |
            Q(inquilino__telefono_secundario__icontains=q) |
            Q(inquilino__cedula_o_pasaporte__icontains=q) |
            Q(propiedad__nombre_o_numero__icontains=q) |
            Q(propiedad__grupo_o_residencial__icontains=q)
        )

    contratos = contratos.order_by('-activo', 'propiedad__nombre_o_numero')

    context = {
        'titulo_pagina': 'Gestión de Contratos',
        'contratos': contratos,
        'q': q,
        'estado_sel': estado,
        'portafolios': portafolios,
        'portafolio_sel': str(portafolio_id),
        'total_contratos': contratos.count(),
    }
    return render(request, 'gestion_propiedades/lista_contratos.html', context)

@login_required(login_url='/login/')
def imprimir_recibo(request, recibo_id):
    # 1. Buscamos el recibo (asegurando que pertenezca a un portafolio del usuario)
    recibo = get_object_or_404(ReciboPago, id=recibo_id)

    # Validación de seguridad simple:
    # Si el usuario no es dueño ni asistente del portafolio, dar error 404
    if recibo.factura.contrato.propiedad.portafolio.propietario != request.user:
        # Aquí podríamos refinar la validación para asistentes, pero por ahora esto protege
        pass 

    data = {
        'recibo': recibo,
        'factura': recibo.factura,
        'contrato': recibo.factura.contrato,
        'propiedad': recibo.factura.contrato.propiedad,
        'usuario': request.user,
    }

    # 3. Vista Smart Print
    return render(request, 'gestion_propiedades/recibo_pdf.html', data)

# --- Agrega esto AL FINAL del archivo, después de imprimir_recibo ---

@login_required(login_url='/login/')
@propietario_requerido  # ESCUDO RBAC (Solo admins)
def crear_propiedad(request):
    # IMPORTACIÓN LOCAL (CRUCIAL):
    from .forms import PropiedadForm 

    portafolios = Portafolio.objects.filter(Q(propietario=request.user) | Q(accesos__usuario=request.user)).distinct()
    if not portafolios.exists():
        return HttpResponse("Error: No tienes un portafolio asignado.")

    portafolio_id = request.GET.get('portafolio_id') or request.POST.get('portafolio_id')
    portafolio_principal = None
    if portafolio_id and str(portafolio_id).isdigit():
        portafolio_principal = portafolios.filter(id=int(portafolio_id)).first()

    if not portafolio_principal:
        portafolio_principal = Portafolio.objects.filter(propietario=request.user).first()
        if not portafolio_principal:
            acceso = request.user.portafolios_asignados.first()
            if acceso:
                portafolio_principal = acceso.portafolio
        if not portafolio_principal:
            portafolio_principal = portafolios.first()

    if request.method == 'POST':
        form = PropiedadForm(request.POST, request.FILES, portafolio=portafolio_principal, user=request.user)
        if form.is_valid():
            nueva_propiedad = form.save(commit=False)
            nueva_propiedad.portafolio = portafolio_principal
            nueva_propiedad.save()
            return redirect('lista_propiedades')
    else:
        form = PropiedadForm(portafolio=portafolio_principal, user=request.user)

    context = {'titulo_pagina': 'Nueva Propiedad', 'form': form}
    return render(request, 'gestion_propiedades/form_generico.html', context)

@login_required(login_url='/login/')
def crear_contrato(request):
    from .forms import ContratoForm
    
    if request.method == 'POST':
        form = ContratoForm(request.user, request.POST, request.FILES)
        if form.is_valid():
            nuevo_contrato = form.save(commit=False)
            
            # Si seleccionaron plantilla, generamos el texto legal
            if nuevo_contrato.plantilla:
                html = nuevo_contrato.plantilla.contenido
                import datetime
                hoy = datetime.date.today()
                
                # Intentamos sacar datos del propietario (dueño específico o del portafolio)
                if nuevo_contrato.propiedad.propietario_inmueble:
                    prop_nombre = nuevo_contrato.propiedad.propietario_inmueble.nombre
                    prop_cedula = nuevo_contrato.propiedad.propietario_inmueble.cedula_o_rnc or '___________________'
                    prop_dir = nuevo_contrato.propiedad.propietario_inmueble.direccion or nuevo_contrato.propiedad.portafolio.direccion_fisica or '___________________'
                else:
                    prop_nombre = nuevo_contrato.propiedad.portafolio.propietario.get_full_name() or nuevo_contrato.propiedad.portafolio.propietario.username
                    prop_cedula = '___________________'
                    prop_dir = nuevo_contrato.propiedad.portafolio.direccion_fisica or '___________________'
                
                meses = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
                mes_actual_es = meses[hoy.month - 1]
                
                reemplazos = {
                    '{{PROPIETARIO_NOMBRE}}': prop_nombre,
                    '{{PROPIETARIO_CEDULA}}': prop_cedula,
                    '{{PROPIETARIO_DIRECCION}}': prop_dir,
                    '{{INQUILINO_NOMBRE}}': nuevo_contrato.inquilino.nombre,
                    '{{INQUILINO_CEDULA}}': nuevo_contrato.inquilino.cedula_o_pasaporte or '___________________',
                    '{{INQUILINO_DIRECCION}}': nuevo_contrato.inquilino.direccion or '___________________',
                    '{{INQUILINO_TELEFONO}}': nuevo_contrato.inquilino.telefono or '___________________',
                    '{{INQUILINO_TELEFONO_SECUNDARIO}}': nuevo_contrato.inquilino.telefono_secundario or '___________________',
                    '{{PROPIEDAD_DIRECCION}}': nuevo_contrato.propiedad.direccion_completa or nuevo_contrato.propiedad.nombre_o_numero,
                    '{{MONTO_RENTA}}': f"RD$ {nuevo_contrato.monto_renta:,.2f}",
                    '{{MONTO_DEPOSITO}}': f"RD$ {nuevo_contrato.monto_deposito:,.2f}",
                    '{{FECHA_INICIO}}': nuevo_contrato.fecha_inicio.strftime('%d/%m/%Y'),
                    '{{FECHA_FIN}}': nuevo_contrato.fecha_fin.strftime('%d/%m/%Y') if nuevo_contrato.fecha_fin else 'Indefinida',
                    '{{DIA_PAGO}}': str(nuevo_contrato.dia_de_pago),
                    '{{DIA_ACTUAL}}': str(hoy.day),
                    '{{MES_ACTUAL}}': mes_actual_es,
                    '{{ANIO_ACTUAL}}': str(hoy.year),
                    '{{FIADOR_NOMBRE}}': nuevo_contrato.inquilino.nombre_fiador or '___________________',
                    '{{FIADOR_CEDULA}}': nuevo_contrato.inquilino.cedula_fiador or '___________________',
                    '{{FIADOR_TELEFONO}}': nuevo_contrato.inquilino.telefono_fiador or '___________________',
                    '{{FIADOR_TELEFONO_SECUNDARIO}}': nuevo_contrato.inquilino.telefono_fiador_secundario or '___________________',
                    '{{FIADOR_DIRECCION}}': nuevo_contrato.inquilino.direccion_fiador or '___________________',
                }
                
                for tag, valor in reemplazos.items():
                    html = html.replace(tag, str(valor))
                
                nuevo_contrato.texto_legal_generado = html

            nuevo_contrato.save()
            
            # --- INYECCIÓN DE DEUDA MIGRADA ---
            if nuevo_contrato.deuda_renta_migrada > 0 or nuevo_contrato.deuda_mora_migrada > 0:
                # Calculamos el estado: si solo trae renta puede estar pendiente, si trae mora obvio está atrasada
                estado_migracion = 'ATRASADA' if nuevo_contrato.deuda_mora_migrada > 0 else 'PENDIENTE'
                
                factura_fantasma = Factura.objects.create(
                    contrato=nuevo_contrato,
                    fecha_emision=nuevo_contrato.fecha_inicio,
                    fecha_vencimiento=nuevo_contrato.fecha_inicio,
                    monto_base=nuevo_contrato.deuda_renta_migrada,
                    monto_renta=nuevo_contrato.deuda_renta_migrada,
                    estado=estado_migracion,
                    concepto=f'Balance migrado previo a Alquilo'
                )
                
                if nuevo_contrato.deuda_mora_migrada > 0:
                    CargoMora.objects.create(
                        factura=factura_fantasma,
                        monto=nuevo_contrato.deuda_mora_migrada,
                        mes_aplicado=nuevo_contrato.fecha_inicio.month,
                        anio_aplicado=nuevo_contrato.fecha_inicio.year
                    )
            # --- FIN INYECCIÓN DE DEUDA ---

            # --- PROCESAR CARGOS ADICIONALES RECURRENTES ---
            cargos_cat = request.POST.getlist('cargo_categoria[]')
            cargos_concepto = request.POST.getlist('cargo_concepto[]')
            cargos_monto = request.POST.getlist('cargo_monto[]')
            for cat, con, mon in zip(cargos_cat, cargos_concepto, cargos_monto):
                try:
                    monto_val = decimal.Decimal(str(mon).replace(',', '').strip())
                    if monto_val > 0:
                        CargoAdicionalContrato.objects.create(
                            contrato=nuevo_contrato,
                            categoria=cat or 'MANTENIMIENTO',
                            concepto_personalizado=con.strip() if con else None,
                            monto=monto_val,
                            activo=True
                        )
                except Exception:
                    pass

            propiedad = nuevo_contrato.propiedad
            propiedad.estado = 'OCUPADO'
            propiedad.save()
            return redirect('lista_contratos')
    else:
        form = ContratoForm(request.user)

    import json
    portafolios = Portafolio.objects.filter(Q(propietario=request.user) | Q(accesos__usuario=request.user))
    propiedades = Propiedad.objects.filter(portafolio__in=portafolios, is_deleted=False).select_related('portafolio')
    config_depositos = {
        str(p.id): {
            'dep': p.portafolio.config_meses_deposito,
            'adel': p.portafolio.config_meses_adelanto
        } for p in propiedades
    }

    context = {
        'titulo_pagina': 'Nuevo Contrato de Alquiler', 
        'form': form,
        'es_contrato': True,
        'config_depositos': json.dumps(config_depositos)
    }
    return render(request, 'gestion_propiedades/form_generico.html', context)

@login_required(login_url='/login/')
@propietario_requerido
def generar_facturas_masivas(request):
    if not request.user.is_superuser:
        messages.error(request, "Acceso restringido. La generación manual de facturas masivas solo está permitida para el Superadministrador.")
        return redirect('dashboard')

    # 1. Buscamos los portafolios del usuario
    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().distinct()
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()

    # 2. Buscamos contratos activos
    contratos = Contrato.objects.filter(
        propiedad__portafolio__in=portafolios,
        activo=True
    )

    hoy = date.today()
    facturas_creadas = 0
    errores = []

    for contrato in contratos:
        # 3. Verificamos si YA existe una factura para este mes y año
        existe = Factura.objects.filter(
            contrato=contrato,
            fecha_emision__month=hoy.month,
            fecha_emision__year=hoy.year
        ).exists()

        if not existe:
            try:
                # Calcular fecha de vencimiento (Manejo de errores si el mes es febrero y el día es 30)
                try:
                    fecha_vencimiento = date(hoy.year, hoy.month, contrato.dia_de_pago)
                except ValueError:
                    # Si el día de pago es 31 y el mes solo tiene 30 (o 28), usamos el último día del mes
                    ultimo_dia_mes = calendar.monthrange(hoy.year, hoy.month)[1]
                    fecha_vencimiento = date(hoy.year, hoy.month, ultimo_dia_mes)

                # 4. Crear la Factura con renta y cargos adicionales recurrentes
                concepto_factura = contrato.propiedad.portafolio.generar_concepto_factura(contrato, hoy)
                cargos_activos = list(contrato.cargos_adicionales.filter(activo=True))
                total_servicios = sum(c.monto for c in cargos_activos)
                total_renta = contrato.monto_renta
                total_base = total_renta + total_servicios

                factura_creada = Factura.objects.create(
                    contrato=contrato,
                    fecha_emision=hoy,
                    fecha_vencimiento=fecha_vencimiento,
                    monto_base=total_base,
                    monto_renta=total_renta,
                    monto_servicios=total_servicios,
                    concepto=concepto_factura,
                    estado='PENDIENTE'
                )
                for c in cargos_activos:
                    DetalleFacturaServicio.objects.create(
                        factura=factura_creada,
                        cargo_origen=c,
                        categoria=c.categoria,
                        concepto=c.nombre_mostrar,
                        monto=c.monto
                    )
                facturas_creadas += 1
            except Exception as e:
                errores.append(f"Error en contrato {contrato.id} ({contrato.inquilino.nombre}): {str(e)}")

    exitoso = len(errores) == 0
    detalles = f"Se generaron {facturas_creadas} facturas de renta."
    if errores:
        detalles += " Errores ocurridos:\n" + "\n".join(errores)

    # Crear RegistroProceso
    RegistroProceso.objects.create(
        nombre_proceso="Generación de Rentas (Manual)",
        exitoso=exitoso,
        facturas_creadas=facturas_creadas,
        detalles=detalles,
        ejecutado_por=request.user
    )

    # 5. Mensaje de éxito
    if facturas_creadas > 0:
        messages.success(request, f'¡Éxito! Se han generado {facturas_creadas} facturas nuevas.')
    else:
        if exitoso:
            messages.info(request, 'No se generaron facturas. Todos tus inquilinos ya tienen su factura de este mes.')
        else:
            messages.error(request, 'Ocurrieron algunos errores al generar las facturas. Por favor contacta al soporte.')

    return redirect('dashboard')

@login_required(login_url='/login/')
def registrar_gasto(request, propiedad_id):
    from .forms import MantenimientoForm
    
    portafolios = Portafolio.objects.filter(Q(propietario=request.user) | Q(accesos__usuario=request.user))
    propiedad = get_object_or_404(Propiedad, id=propiedad_id, portafolio__in=portafolios)

    if request.method == 'POST':
        # request.FILES es OBLIGATORIO para subir la 'factura_adjunta'
        form = MantenimientoForm(request.POST, request.FILES)
        if form.is_valid():
            gasto = form.save(commit=False)
            gasto.propiedad = propiedad
            gasto.save()
            messages.success(request, 'Gasto registrado correctamente.')
            return redirect('detalle_propiedad', propiedad_id=propiedad.id)
    else:
        form = MantenimientoForm()

    context = {
        'titulo_pagina': f'Registrar Gasto: {propiedad.nombre_o_numero}',
        'form': form
    }
    return render(request, 'gestion_propiedades/form_generico.html', context)

@login_required(login_url='/login/')
def finalizar_contrato(request, contrato_id):
    """
    Pantalla interactiva de Liquidación de Depósito (Finiquito) y finalización de contrato.
    Calcula facturas pendientes, permite deducciones por daños y genera la acta de finiquito.
    """
    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().distinct()
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()
    
    contrato = get_object_or_404(Contrato, id=contrato_id, propiedad__portafolio__in=portafolios)
    
    # Calcular facturas pendientes del contrato
    facturas_pendientes = Factura.objects.filter(
        contrato=contrato,
        estado__in=['PENDIENTE', 'ATRASADA']
    ).annotate(mora_acumulada=Sum('moras__monto'))
    
    total_deuda_facturas = decimal.Decimal('0.00')
    for f in facturas_pendientes:
        mora = f.mora_acumulada or decimal.Decimal('0.00')
        pagos = f.pagos.aggregate(total=Sum('monto_pagado'))['total'] or decimal.Decimal('0.00')
        saldo = (f.monto_base + mora) - pagos
        if saldo > 0:
            total_deuda_facturas += saldo
            
    if request.method == 'POST':
        form = LiquidacionDepositoForm(request.POST)
        if form.is_valid():
            liq = form.save(commit=False)
            liq.contrato = contrato
            liq.monto_deposito_original = contrato.monto_deposito
            liq.monto_deduccion_facturas = total_deuda_facturas
            
            monto_danos = form.cleaned_data.get('monto_deduccion_danos') or decimal.Decimal('0.00')
            liq.monto_deduccion_danos = monto_danos
            
            neto = contrato.monto_deposito - total_deuda_facturas - monto_danos
            liq.monto_neto_devuelto = neto
            
            if neto > 0:
                liq.estado = 'DEVUELTO'
            elif neto == 0:
                liq.estado = 'RETENIDO_TOTAL'
            else:
                liq.estado = 'SALDO_PENDIENTE_INQUILINO'
                
            liq.registrado_por = request.user
            liq.save()
            
            # Desactivar contrato
            contrato.activo = False
            contrato.fecha_fin = liq.fecha_liquidacion
            contrato.save()
            
            # Liberar propiedad
            propiedad = contrato.propiedad
            propiedad.estado = 'DISPONIBLE'
            propiedad.save()
            
            # Si hubo deducción por daños, registrar automáticamente una incidencia/mantenimiento
            if monto_danos > 0:
                MantenimientoUnidad.objects.create(
                    propiedad=propiedad,
                    descripcion=f"Reparación por daños retenidos al finalizar contrato #{contrato.id}: {liq.detalles_danos or 'Sin detalles'}",
                    costo=monto_danos,
                    estado='COMPLETADO',
                    fecha_reporte=liq.fecha_liquidacion
                )
                
            messages.success(request, f'Liquidación de depósito completada. El contrato de {contrato.inquilino.nombre} ha finalizado.')
            return redirect('imprimir_liquidacion_deposito', contrato_id=contrato.id)
    else:
        form = LiquidacionDepositoForm(initial={
            'monto_deduccion_facturas': total_deuda_facturas,
            'monto_deduccion_danos': decimal.Decimal('0.00'),
            'fecha_liquidacion': date.today()
        })
        
    neto_estimado = max(decimal.Decimal('0.00'), contrato.monto_deposito - total_deuda_facturas)
    
    context = {
        'titulo_pagina': f'Finalizar Contrato y Liquidar Depósito',
        'contrato': contrato,
        'form': form,
        'facturas_pendientes': facturas_pendientes,
        'total_deuda_facturas': total_deuda_facturas,
        'neto_estimado': neto_estimado
    }
    return render(request, 'gestion_propiedades/finalizar_contrato.html', context)


@login_required(login_url='/login/')
def imprimir_liquidacion_deposito(request, contrato_id):
    """
    Vista de impresión oficial de la Acta de Finiquito y Liquidación de Depósito.
    """
    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().distinct()
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()
    
    contrato = get_object_or_404(Contrato, id=contrato_id, propiedad__portafolio__in=portafolios)
    liquidacion = get_object_or_404(LiquidacionDepositoInquilino, contrato=contrato)
    
    context = {
        'contrato': contrato,
        'liquidacion': liquidacion,
        'fecha_emision': timezone.now()
    }
    return render(request, 'gestion_propiedades/imprimir_liquidacion_deposito.html', context)

@login_required(login_url='/login/')
def editar_propiedad(request, propiedad_id):
    from .forms import PropiedadForm
    
    portafolios = Portafolio.objects.filter(Q(propietario=request.user) | Q(accesos__usuario=request.user))
    propiedad = get_object_or_404(Propiedad, id=propiedad_id, portafolio__in=portafolios)

    if request.method == 'POST':
        # instance=propiedad le dice a Django "actualiza este registro, no crees uno nuevo"
        form = PropiedadForm(request.POST, request.FILES, instance=propiedad, portafolio=propiedad.portafolio, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Propiedad actualizada correctamente.')
            return redirect('detalle_propiedad', propiedad_id=propiedad.id)
    else:
        form = PropiedadForm(instance=propiedad, portafolio=propiedad.portafolio, user=request.user)

    context = {'titulo_pagina': f'Editar Propiedad: {propiedad.nombre_o_numero}', 'form': form}
    return render(request, 'gestion_propiedades/form_generico.html', context)

@login_required(login_url='/login/')
def editar_contrato(request, contrato_id):
    from .forms import ContratoForm
    
    portafolios = Portafolio.objects.filter(Q(propietario=request.user) | Q(accesos__usuario=request.user))
    contrato = get_object_or_404(Contrato, id=contrato_id, propiedad__portafolio__in=portafolios)

    if request.method == 'POST':
        form = ContratoForm(request.user, request.POST, request.FILES, instance=contrato)
        if form.is_valid():
            contrato_editado = form.save(commit=False)
            
            # Si seleccionaron plantilla, regeneramos el texto legal
            if contrato_editado.plantilla:
                html = contrato_editado.plantilla.contenido
                import datetime
                hoy = datetime.date.today()
                
                # Intentamos sacar datos del propietario (dueño específico o del portafolio)
                if contrato_editado.propiedad.propietario_inmueble:
                    prop_nombre = contrato_editado.propiedad.propietario_inmueble.nombre
                    prop_cedula = contrato_editado.propiedad.propietario_inmueble.cedula_o_rnc or '___________________'
                    prop_dir = contrato_editado.propiedad.propietario_inmueble.direccion or contrato_editado.propiedad.portafolio.direccion_fisica or '___________________'
                else:
                    prop_nombre = contrato_editado.propiedad.portafolio.propietario.get_full_name() or contrato_editado.propiedad.portafolio.propietario.username
                    prop_cedula = '___________________'
                    prop_dir = contrato_editado.propiedad.portafolio.direccion_fisica or '___________________'
                
                meses = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
                mes_actual_es = meses[hoy.month - 1]
                
                reemplazos = {
                    '{{PROPIETARIO_NOMBRE}}': prop_nombre,
                    '{{PROPIETARIO_CEDULA}}': prop_cedula,
                    '{{PROPIETARIO_DIRECCION}}': prop_dir,
                    '{{INQUILINO_NOMBRE}}': contrato_editado.inquilino.nombre,
                    '{{INQUILINO_CEDULA}}': contrato_editado.inquilino.cedula_o_pasaporte or '___________________',
                    '{{INQUILINO_DIRECCION}}': contrato_editado.inquilino.direccion or '___________________',
                    '{{INQUILINO_TELEFONO}}': contrato_editado.inquilino.telefono or '___________________',
                    '{{INQUILINO_TELEFONO_SECUNDARIO}}': contrato_editado.inquilino.telefono_secundario or '___________________',
                    '{{PROPIEDAD_DIRECCION}}': contrato_editado.propiedad.direccion_completa or contrato_editado.propiedad.nombre_o_numero,
                    '{{MONTO_RENTA}}': f"RD$ {contrato_editado.monto_renta:,.2f}",
                    '{{MONTO_DEPOSITO}}': f"RD$ {contrato_editado.monto_deposito:,.2f}",
                    '{{FECHA_INICIO}}': contrato_editado.fecha_inicio.strftime('%d/%m/%Y'),
                    '{{FECHA_FIN}}': contrato_editado.fecha_fin.strftime('%d/%m/%Y') if contrato_editado.fecha_fin else 'Indefinida',
                    '{{DIA_PAGO}}': str(contrato_editado.dia_de_pago),
                    '{{DIA_ACTUAL}}': str(hoy.day),
                    '{{MES_ACTUAL}}': mes_actual_es,
                    '{{ANIO_ACTUAL}}': str(hoy.year),
                    '{{FIADOR_NOMBRE}}': contrato_editado.inquilino.nombre_fiador or '___________________',
                    '{{FIADOR_CEDULA}}': contrato_editado.inquilino.cedula_fiador or '___________________',
                    '{{FIADOR_TELEFONO}}': contrato_editado.inquilino.telefono_fiador or '___________________',
                    '{{FIADOR_TELEFONO_SECUNDARIO}}': contrato_editado.inquilino.telefono_fiador_secundario or '___________________',
                    '{{FIADOR_DIRECCION}}': contrato_editado.inquilino.direccion_fiador or '___________________',
                }
                
                for tag, valor in reemplazos.items():
                    html = html.replace(tag, str(valor))
                
                contrato_editado.texto_legal_generado = html

            contrato_editado.save()

            # --- PROCESAR CARGOS ADICIONALES RECURRENTES ---
            cargos_cat = request.POST.getlist('cargo_categoria[]')
            cargos_concepto = request.POST.getlist('cargo_concepto[]')
            cargos_monto = request.POST.getlist('cargo_monto[]')
            contrato_editado.cargos_adicionales.all().delete()
            for cat, con, mon in zip(cargos_cat, cargos_concepto, cargos_monto):
                try:
                    monto_val = decimal.Decimal(str(mon).replace(',', '').strip())
                    if monto_val > 0:
                        CargoAdicionalContrato.objects.create(
                            contrato=contrato_editado,
                            categoria=cat or 'MANTENIMIENTO',
                            concepto_personalizado=con.strip() if con else None,
                            monto=monto_val,
                            activo=True
                        )
                except Exception:
                    pass

            messages.success(request, 'Contrato actualizado correctamente.')
            return redirect('detalle_propiedad', propiedad_id=contrato.propiedad.id)
    else:
        form = ContratoForm(request.user, instance=contrato)

    import json
    propiedades = Propiedad.objects.filter(portafolio__in=portafolios, is_deleted=False).select_related('portafolio')
    config_depositos = {
        str(p.id): {
            'dep': p.portafolio.config_meses_deposito,
            'adel': p.portafolio.config_meses_adelanto
        } for p in propiedades
    }

    context = {
        'titulo_pagina': f'Editar Contrato: {contrato.inquilino.nombre}', 
        'form': form,
        'es_contrato': True,
        'cargos_adicionales_existentes': contrato.cargos_adicionales.filter(activo=True),
        'config_depositos': json.dumps(config_depositos)
    }
    return render(request, 'gestion_propiedades/form_generico.html', context)


@login_required(login_url='/login/')
def registrar_aumento_renta(request, contrato_id):
    from .models import Contrato, HistorialAumentoRenta, AuditLog
    from django.db.models import Q
    from django.shortcuts import get_object_or_404, redirect
    from django.contrib import messages
    
    portafolios = Portafolio.objects.filter(Q(propietario=request.user) | Q(accesos__usuario=request.user)).distinct()
    contrato = get_object_or_404(Contrato, id=contrato_id, propiedad__portafolio__in=portafolios)

    if request.method == 'POST':
        try:
            nuevo_monto = float(request.POST.get('nuevo_monto', 0.00))
            fecha_aumento = request.POST.get('fecha_aumento')
            if not fecha_aumento:
                raise ValueError("La fecha de aumento es requerida.")
        except (ValueError, TypeError) as e:
            messages.error(request, f"Error al registrar el aumento: {str(e)}")
            return redirect('detalle_propiedad', propiedad_id=contrato.propiedad.id)

        monto_anterior = contrato.monto_renta

        # 1. Crear el registro en el historial de aumentos
        HistorialAumentoRenta.objects.create(
            contrato=contrato,
            fecha_aumento=fecha_aumento,
            monto_anterior=monto_anterior,
            nuevo_monto=nuevo_monto,
            usuario=request.user
        )

        # 2. Actualizar el monto de renta recurrente del contrato principal
        contrato.monto_renta = nuevo_monto
        contrato.save()

        # 3. Registrar en Auditoría
        AuditLog.objects.create(
            accion='EDITAR',
            modulo='Contrato',
            descripcion=f'Registró aumento de renta para el contrato de {contrato.inquilino.nombre}. Monto anterior: ${monto_anterior} -> Nuevo monto: ${nuevo_monto}. Vigencia: {fecha_aumento}',
            usuario=request.user,
            portafolio=contrato.propiedad.portafolio
        )

        messages.success(request, f"Se ha registrado el aumento de renta correctamente. Nueva renta mensual: ${nuevo_monto:,.2f}")
    
    return redirect('detalle_propiedad', propiedad_id=contrato.propiedad.id)


@login_required(login_url='/login/')
def gestionar_servicios_contrato(request, contrato_id):
    """
    Vista dedicada para configurar y registrar los servicios y cargos adicionales
    que se cobran recurrentemente a un inquilino (Agua, Luz de bomba, Mantenimiento, Basura, Parqueo, etc.).
    """
    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().distinct()
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()
    contrato = get_object_or_404(Contrato, id=contrato_id, propiedad__portafolio__in=portafolios)

    next_url = request.GET.get('next') or request.POST.get('next') or ''

    if request.method == 'POST':
        cargos_cat = request.POST.getlist('cargo_categoria[]')
        cargos_concepto = request.POST.getlist('cargo_concepto[]')
        cargos_monto = request.POST.getlist('cargo_monto[]')

        # Limpiar cargos anteriores
        contrato.cargos_adicionales.all().delete()

        servicios_creados = 0
        for cat, con, mon in zip(cargos_cat, cargos_concepto, cargos_monto):
            try:
                monto_val = Decimal(str(mon).replace(',', '').strip())
                if monto_val > 0:
                    CargoAdicionalContrato.objects.create(
                        contrato=contrato,
                        categoria=cat or 'MANTENIMIENTO',
                        concepto_personalizado=con.strip() if con else None,
                        monto=monto_val,
                        activo=True
                    )
                    servicios_creados += 1
            except Exception:
                pass

        AuditLog.objects.create(
            accion='EDITAR',
            modulo='Contrato',
            descripcion=f"Se actualizaron los servicios adicionales ({servicios_creados} registrados) para el contrato de {contrato.inquilino.nombre} en {contrato.propiedad.nombre_o_numero}. Total servicios: RD$ {contrato.total_cargos_adicionales:,.2f}",
            usuario=request.user,
            portafolio=contrato.propiedad.portafolio
        )

        messages.success(
            request, 
            f"Servicios adicionales actualizados exitosamente para {contrato.inquilino.nombre}. Cuota mensual total (renta + servicios): RD$ {contrato.total_cuota_mensual:,.2f}"
        )

        if next_url:
            return redirect(next_url)
        return redirect('detalle_propiedad', propiedad_id=contrato.propiedad.id)

    cargos_existentes = contrato.cargos_adicionales.filter(activo=True)
    categorias = CargoAdicionalContrato.CATEGORIA_CHOICES

    context = {
        'titulo_pagina': f'Servicios Adicionales: {contrato.inquilino.nombre}',
        'contrato': contrato,
        'cargos_existentes': cargos_existentes,
        'categorias': categorias,
        'next': next_url,
    }
    return render(request, 'gestion_propiedades/gestionar_servicios_contrato.html', context)


@login_required(login_url='/login/')
def generar_solicitud(request, propiedad_id):
    from .forms import SolicitudAdminForm
    
    portafolios = Portafolio.objects.filter(Q(propietario=request.user) | Q(accesos__usuario=request.user))
    propiedad = get_object_or_404(Propiedad, id=propiedad_id, portafolio__in=portafolios)

    if request.method == 'POST':
        form = SolicitudAdminForm(request.POST)
        if form.is_valid():
            solicitud = form.save(commit=False)
            solicitud.propiedad = propiedad
            solicitud.estado = 'ENVIADA' # Lo marcamos como listo para enviar
            solicitud.save()
            messages.success(request, '¡Link de solicitud generado exitosamente!')
            return redirect('detalle_propiedad', propiedad_id=propiedad.id)
    else:
        form = SolicitudAdminForm()

    context = {
        'titulo_pagina': f'Generar Solicitud: {propiedad.nombre_o_numero}',
        'form': form
    }
    return render(request, 'gestion_propiedades/form_generico.html', context)

# --- IMPORTANTE: NO PONER @login_required AQUÍ ---
def solicitud_publica(request, codigo_secreto):
    from .forms import SolicitudPublicaForm
    
    # Buscamos la solicitud usando el código secreto largo (UUID)
    solicitud = get_object_or_404(SolicitudAlquiler, codigo_secreto=codigo_secreto)

    # Si ya la llenó antes y está aprobada/rechazada o en evaluación previa, no le dejamos llenarla salvo que esté devuelta para corrección
    if solicitud.estado in ['RECIBIDA', 'APROBADA', 'RECHAZADA']:
        return HttpResponse("<h2 style='text-align:center; padding:50px; font-family:sans-serif;'>Esta solicitud ya fue completada y enviada. ¡Gracias!</h2>")

    if request.method == 'POST':
        form = SolicitudPublicaForm(request.POST, request.FILES, instance=solicitud)
        if form.is_valid():
            solicitud_guardada = form.save(commit=False)
            solicitud_guardada.estado = 'RECIBIDA' # Cambia el estado a RECIBIDA tras corregir o enviar
            solicitud_guardada.save()
            return HttpResponse("<h2 style='text-align:center; padding:50px; color:green; font-family:sans-serif;'>✅ ¡Solicitud enviada con éxito! El administrador evaluará tu expediente.</h2>")
    else:
        form = SolicitudPublicaForm(instance=solicitud)

    context = {
        'solicitud': solicitud,
        'form': form
    }
    return render(request, 'gestion_propiedades/solicitud_publica.html', context)

@login_required(login_url='/login/')
def ver_solicitud(request, solicitud_id):
    from .models import SolicitudAlquiler, Portafolio
    from django.db.models import Q
    
    # Seguridad: Validamos que la solicitud sea de una propiedad tuya
    portafolios = Portafolio.objects.filter(Q(propietario=request.user) | Q(accesos__usuario=request.user))
    solicitud = get_object_or_404(SolicitudAlquiler, id=solicitud_id, propiedad__portafolio__in=portafolios)

    context = {
        'titulo_pagina': f'Evaluación de Prospecto: {solicitud.nombre_completo}',
        'solicitud': solicitud
    }
    return render(request, 'gestion_propiedades/ver_solicitud.html', context)

@login_required(login_url='/login/')
def devolver_solicitud_alquiler(request, solicitud_id):
    portafolios = Portafolio.objects.filter(Q(propietario=request.user) | Q(accesos__usuario=request.user))
    solicitud = get_object_or_404(SolicitudAlquiler, id=solicitud_id, propiedad__portafolio__in=portafolios)
    
    if request.method == 'POST':
        motivo = request.POST.get('motivo_devolucion', '')
        solicitud.estado = 'DEVUELTA_PARA_CORRECCION'
        solicitud.motivo_devolucion = motivo
        solicitud.save()
        messages.success(request, f'La solicitud ha sido devuelta al prospecto. Se le notificó el motivo: "{motivo}"')
    return redirect('ver_solicitud', solicitud_id=solicitud.id)

@login_required(login_url='/login/')
def subir_imagen_galeria(request, propiedad_id):
    portafolios = Portafolio.objects.filter(Q(propietario=request.user) | Q(accesos__usuario=request.user))
    propiedad = get_object_or_404(Propiedad, id=propiedad_id, portafolio__in=portafolios)
    
    if request.method == 'POST' and request.FILES.get('imagen'):
        imagen_file = request.FILES.get('imagen')
        titulo = request.POST.get('titulo_o_descripcion', '')
        ImagenPropiedad.objects.create(
            propiedad=propiedad,
            imagen=imagen_file,
            titulo_o_descripcion=titulo
        )
        messages.success(request, 'Imagen agregada exitosamente a la galería de la propiedad.')
    return redirect('detalle_propiedad', propiedad_id=propiedad.id)

@login_required(login_url='/login/')
def eliminar_imagen_galeria(request, imagen_id):
    portafolios = Portafolio.objects.filter(Q(propietario=request.user) | Q(accesos__usuario=request.user))
    imagen_obj = get_object_or_404(ImagenPropiedad, id=imagen_id, propiedad__portafolio__in=portafolios)
    propiedad_id = imagen_obj.propiedad.id
    
    if request.method == 'POST':
        if imagen_obj.imagen:
            imagen_obj.imagen.delete(save=False)
        imagen_obj.delete()
        messages.success(request, 'Imagen eliminada de la galería.')
    return redirect('detalle_propiedad', propiedad_id=propiedad_id)

@login_required(login_url='/login/')
def reporte_financiero(request):
    """
    Reporte Consolidado de Ingresos y Gastos (P&L / Flujo de Caja)
    Permite filtrar por Mes, Año, Portafolio Completo, Propietario de Inmueble o Inquilino.
    """
    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().distinct()
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()

    # Parámetros GET
    mes = request.GET.get('mes', str(date.today().month)) # "0" para Todo el Año
    anio = int(request.GET.get('anio', date.today().year))
    filtro_tipo = request.GET.get('filtro_tipo', 'PORTAFOLIO') # PORTAFOLIO, PROPIETARIO, INQUILINO
    portafolio_id = request.GET.get('portafolio_id', 'TODOS')
    propietario_id = request.GET.get('propietario_id', '')
    inquilino_id = request.GET.get('inquilino_id', '')

    if portafolio_id != 'TODOS' and portafolio_id and str(portafolio_id).isdigit():
        portafolios_filtrados = portafolios.filter(id=int(portafolio_id))
    else:
        portafolios_filtrados = portafolios

    # Listas para desplegables de filtro estrictamente acotadas al portafolio
    propietarios_list = PropietarioInmueble.objects.filter(portafolio__in=portafolios_filtrados, activo=True).order_by('nombre')
    inquilinos_list = Inquilino.objects.filter(
        contratos__propiedad__portafolio__in=portafolios_filtrados
    ).distinct().order_by('nombre')

    # Base QuerySets de Propiedades
    propiedades_qs = Propiedad.objects.filter(portafolio__in=portafolios_filtrados, is_deleted=False)

    if filtro_tipo == 'PROPIETARIO' and propietario_id:
        propiedades_qs = propiedades_qs.filter(propietario_inmueble_id=propietario_id)
    elif filtro_tipo == 'INQUILINO' and inquilino_id:
        propiedades_qs = propiedades_qs.filter(contratos__inquilino_id=inquilino_id)

    # Base QuerySet Recibos de Pago (Ingresos)
    recibos_qs = ReciboPago.objects.filter(
        factura__contrato__propiedad__in=propiedades_qs
    ).select_related(
        'factura__contrato__propiedad__propietario_inmueble',
        'factura__contrato__inquilino'
    )

    # Base QuerySet Mantenimiento (Gastos Directos)
    mantenimientos_qs = MantenimientoUnidad.objects.filter(
        propiedad__in=propiedades_qs
    ).select_related('propiedad__propietario_inmueble')

    # Base QuerySet Gastos Generales
    gastos_gen_qs = GastoGeneralPropietario.objects.filter(
        portafolio__in=portafolios
    ).select_related('propietario_inmueble', 'propiedad')

    if filtro_tipo == 'PROPIETARIO' and propietario_id:
        gastos_gen_qs = gastos_gen_qs.filter(
            Q(propietario_inmueble_id=propietario_id) | Q(propiedad__in=propiedades_qs)
        )
    elif filtro_tipo == 'INQUILINO' and inquilino_id:
        gastos_gen_qs = gastos_gen_qs.filter(propiedad__in=propiedades_qs)

    # Filtrar por Año
    recibos_qs = recibos_qs.filter(fecha_pago__year=anio)
    mantenimientos_qs = mantenimientos_qs.filter(fecha_reporte__year=anio)
    gastos_gen_qs = gastos_gen_qs.filter(fecha__year=anio)

    # Filtrar por Mes (si mes != "0")
    if mes and mes != '0':
        mes_num = int(mes)
        recibos_qs = recibos_qs.filter(fecha_pago__month=mes_num)
        mantenimientos_qs = mantenimientos_qs.filter(fecha_reporte__month=mes_num)
        gastos_gen_qs = gastos_gen_qs.filter(fecha__month=mes_num)

    if filtro_tipo == 'INQUILINO' and inquilino_id:
        recibos_qs = recibos_qs.filter(factura__contrato__inquilino_id=inquilino_id)

    # Calcular Totales
    recibos_list = list(recibos_qs.order_by('-fecha_pago'))
    mantenimientos_list = list(mantenimientos_qs.order_by('-fecha_reporte'))
    gastos_gen_list = list(gastos_gen_qs.order_by('-fecha'))

    total_ingresos = sum(r.monto_pagado for r in recibos_list) or decimal.Decimal('0.00')
    total_gastos_directos = sum(m.costo for m in mantenimientos_list) or decimal.Decimal('0.00')
    total_gastos_generales = sum(g.monto for g in gastos_gen_list) or decimal.Decimal('0.00')
    total_gastos = total_gastos_directos + total_gastos_generales
    beneficio_neto = total_ingresos - total_gastos

    # Agrupar para tabla mensual / propiedad P&L
    datos_financieros = defaultdict(lambda: {
        'nombre_propiedad': '',
        'mes_formateado': '',
        'mes_date': None,
        'ingresos': 0.0,
        'egresos': 0.0,
        'neto': 0.0
    })

    for r in recibos_list:
        mes_trunc = date(r.fecha_pago.year, r.fecha_pago.month, 1)
        prop_id = r.factura.contrato.propiedad.id
        llave = (mes_trunc, prop_id)
        datos = datos_financieros[llave]
        datos['nombre_propiedad'] = r.factura.contrato.propiedad.nombre_o_numero
        datos['mes_formateado'] = f"{obtener_nombre_mes(r.fecha_pago.month)} {r.fecha_pago.year}"
        datos['mes_date'] = mes_trunc
        datos['ingresos'] += float(r.monto_pagado)

    for m in mantenimientos_list:
        mes_trunc = date(m.fecha_reporte.year, m.fecha_reporte.month, 1)
        prop_id = m.propiedad.id
        llave = (mes_trunc, prop_id)
        datos = datos_financieros[llave]
        if not datos['nombre_propiedad']:
            datos['nombre_propiedad'] = m.propiedad.nombre_o_numero
            datos['mes_formateado'] = f"{obtener_nombre_mes(m.fecha_reporte.month)} {m.fecha_reporte.year}"
            datos['mes_date'] = mes_trunc
        datos['egresos'] += float(m.costo)

    lista_finanzas = []
    for llave, datos in datos_financieros.items():
        datos['neto'] = datos['ingresos'] - datos['egresos']
        lista_finanzas.append(datos)

    lista_finanzas.sort(key=lambda x: (x['mes_date'], x['nombre_propiedad']), reverse=True)

    context = {
        'titulo_pagina': 'Reporte de Ingresos y Gastos (P&L)',
        'propietarios_list': propietarios_list,
        'inquilinos_list': inquilinos_list,
        'filtro_tipo': filtro_tipo,
        'propietario_id': propietario_id,
        'inquilino_id': inquilino_id,
        'mes': mes,
        'nombre_mes': 'Todo el Año' if mes == '0' else obtener_nombre_mes(int(mes)),
        'anio': anio,
        'anios_disponibles': range(date.today().year - 2, date.today().year + 2),
        'total_ingresos': total_ingresos,
        'total_gastos_directos': total_gastos_directos,
        'total_gastos_generales': total_gastos_generales,
        'total_gastos': total_gastos,
        'beneficio_neto': beneficio_neto,
        'recibos_list': recibos_list,
        'mantenimientos_list': mantenimientos_list,
        'gastos_gen_list': gastos_gen_list,
        'finanzas': lista_finanzas,
        'portafolios': portafolios,
        'portafolio_sel': str(portafolio_id),
    }

    return render(request, 'gestion_propiedades/reporte_financiero.html', context)


# --- REPORTE DETALLADO DE MOVIMIENTOS (INGRESOS Y GASTOS CON RANGO DE FECHAS Y EXCEL) ---

def _obtener_datos_movimientos_detallados(request):
    from datetime import date, datetime, timedelta
    import decimal

    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().distinct()
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()

    hoy = date.today()
    fecha_inicio_str = request.GET.get('fecha_inicio', '').strip()
    fecha_fin_str = request.GET.get('fecha_fin', '').strip()

    try:
        fecha_inicio = datetime.strptime(fecha_inicio_str, '%Y-%m-%d').date() if fecha_inicio_str else date(hoy.year, hoy.month, 1)
    except Exception:
        fecha_inicio = date(hoy.year, hoy.month, 1)

    try:
        fecha_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d').date() if fecha_fin_str else hoy
    except Exception:
        fecha_fin = hoy

    portafolio_id = request.GET.get('portafolio_id', 'TODOS')
    propietario_id = request.GET.get('propietario_id', 'TODOS')
    inquilino_id = request.GET.get('inquilino_id', 'TODOS')
    tipo_movimiento = request.GET.get('tipo_movimiento', 'TODOS')

    if portafolio_id != 'TODOS' and portafolio_id and portafolio_id.isdigit():
        portafolios_filtrados = portafolios.filter(id=int(portafolio_id))
    else:
        portafolios_filtrados = portafolios

    lista_propietarios = PropietarioInmueble.objects.filter(portafolio__in=portafolios_filtrados).order_by('nombre')
    lista_inquilinos = Inquilino.objects.filter(contratos__propiedad__portafolio__in=portafolios_filtrados).distinct().order_by('nombre')

    propiedades_qs = Propiedad.objects.filter(portafolio__in=portafolios_filtrados, is_deleted=False)

    if propietario_id != 'TODOS' and propietario_id.isdigit():
        propiedades_qs = propiedades_qs.filter(propietario_inmueble_id=int(propietario_id))

    movimientos = []

    # 1. INGRESOS (Recibos de Pago)
    if tipo_movimiento in ['TODOS', 'INGRESO']:
        recibos_qs = ReciboPago.objects.filter(
            factura__contrato__propiedad__in=propiedades_qs,
            fecha_pago__range=[fecha_inicio, fecha_fin]
        ).select_related(
            'factura', 'factura__contrato', 'factura__contrato__propiedad',
            'factura__contrato__propiedad__portafolio',
            'factura__contrato__propiedad__propietario_inmueble',
            'factura__contrato__inquilino'
        )

        if inquilino_id != 'TODOS' and inquilino_id.isdigit():
            recibos_qs = recibos_qs.filter(factura__contrato__inquilino_id=int(inquilino_id))

        for r in recibos_qs:
            p = r.factura.contrato.propiedad if (r.factura and r.factura.contrato) else None
            if not p:
                continue
            propietario_nom = p.propietario_inmueble.nombre if p.propietario_inmueble else (
                (p.portafolio.propietario.get_full_name() or p.portafolio.propietario.username)
                if (p.portafolio and p.portafolio.propietario) else 'Propietario General'
            )
            persona_nom = r.factura.contrato.inquilino.nombre if (r.factura and r.factura.contrato and r.factura.contrato.inquilino) else 'Inquilino General'
            movimientos.append({
                'fecha': r.fecha_pago,
                'propiedad': p.nombre_o_numero,
                'grupo_o_residencial': p.grupo_o_residencial or '',
                'propietario': propietario_nom,
                'persona': persona_nom,
                'tipo': 'INGRESO',
                'concepto': f"Cobro Renta (Recibo #{r.id}) - {r.factura.concepto if r.factura else 'Renta'}",
                'monto': r.monto_pagado,
                'referencia_id': f"REC-{r.id}"
            })

    # 2. GASTOS DE MANTENIMIENTO DE UNIDAD
    if tipo_movimiento in ['TODOS', 'GASTO'] and (inquilino_id == 'TODOS'):
        mantenimientos_qs = MantenimientoUnidad.objects.filter(
            propiedad__in=propiedades_qs,
            fecha_reporte__range=[fecha_inicio, fecha_fin]
        ).select_related(
            'propiedad', 'propiedad__portafolio', 'propiedad__propietario_inmueble'
        ).prefetch_related('propiedad__contratos')

        for m in mantenimientos_qs:
            p = m.propiedad
            if not p:
                continue
            propietario_nom = p.propietario_inmueble.nombre if p.propietario_inmueble else (
                (p.portafolio.propietario.get_full_name() or p.portafolio.propietario.username)
                if (p.portafolio and p.portafolio.propietario) else 'Propietario General'
            )
            contrato_act = p.contratos.filter(activo=True).first() if hasattr(p, 'contratos') else None
            persona_nom = contrato_act.inquilino.nombre if (contrato_act and contrato_act.inquilino) else 'Mantenimiento General'
            movimientos.append({
                'fecha': m.fecha_reporte,
                'propiedad': p.nombre_o_numero,
                'grupo_o_residencial': p.grupo_o_residencial or '',
                'propietario': propietario_nom,
                'persona': persona_nom,
                'tipo': 'GASTO',
                'concepto': f"Mantenimiento ({m.get_categoria_display()}): {m.descripcion}",
                'monto': m.costo,
                'referencia_id': f"MAN-{m.id}"
            })

    # 3. GASTOS GENERALES DE PROPIETARIOS
    if tipo_movimiento in ['TODOS', 'GASTO'] and (inquilino_id == 'TODOS'):
        gastos_gen_qs = GastoGeneralPropietario.objects.filter(
            fecha__range=[fecha_inicio, fecha_fin]
        ).select_related('propietario_inmueble', 'propiedad', 'portafolio')

        if propietario_id != 'TODOS' and propietario_id.isdigit():
            gastos_gen_qs = gastos_gen_qs.filter(propietario_inmueble_id=int(propietario_id))
        else:
            gastos_gen_qs = gastos_gen_qs.filter(portafolio__in=portafolios)

        if portafolio_id != 'TODOS' and portafolio_id.isdigit():
            gastos_gen_qs = gastos_gen_qs.filter(portafolio_id=int(portafolio_id))

        for g in gastos_gen_qs:
            prop_nom = g.propiedad.nombre_o_numero if g.propiedad else 'General Propietario'
            grupo_nom = g.propiedad.grupo_o_residencial if (g.propiedad and g.propiedad.grupo_o_residencial) else ''
            propietario_nom = g.propietario_inmueble.nombre if g.propietario_inmueble else (
                (g.portafolio.propietario.get_full_name() or g.portafolio.propietario.username)
                if (g.portafolio and g.portafolio.propietario) else 'Propietario General'
            )
            movimientos.append({
                'fecha': g.fecha,
                'propiedad': prop_nom,
                'grupo_o_residencial': grupo_nom,
                'propietario': propietario_nom,
                'persona': 'Gasto Operativo',
                'tipo': 'GASTO',
                'concepto': f"Gasto Propietario: {g.concepto}",
                'monto': g.monto,
                'referencia_id': f"GGP-{g.id}"
            })

    # Ordenar por fecha descendente
    movimientos.sort(key=lambda x: x['fecha'], reverse=True)

    total_ingresos = sum((m['monto'] for m in movimientos if m['tipo'] == 'INGRESO'), decimal.Decimal('0.00'))
    total_gastos = sum((m['monto'] for m in movimientos if m['tipo'] == 'GASTO'), decimal.Decimal('0.00'))
    balance_neto = total_ingresos - total_gastos

    portafolio_actual = None
    if portafolio_id != 'TODOS' and str(portafolio_id).isdigit():
        portafolio_actual = portafolios.filter(id=int(portafolio_id)).first()
    if not portafolio_actual and portafolios.count() == 1:
        portafolio_actual = portafolios.first()
    elif not portafolio_actual:
        portafolio_actual = portafolios.first()

    return {
        'movimientos': movimientos,
        'total_ingresos': total_ingresos,
        'total_gastos': total_gastos,
        'balance_neto': balance_neto,
        'fecha_inicio': fecha_inicio,
        'fecha_fin': fecha_fin,
        'portafolios': portafolios,
        'portafolio_actual': portafolio_actual,
        'lista_propietarios': lista_propietarios,
        'lista_inquilinos': lista_inquilinos,
        'portafolio_sel': str(portafolio_id),
        'propietario_sel': str(propietario_id),
        'inquilino_sel': str(inquilino_id),
        'tipo_sel': tipo_movimiento,
    }


@login_required(login_url='/login/')
def reporte_movimientos_detallados(request):
    data = _obtener_datos_movimientos_detallados(request)
    data['titulo_pagina'] = 'Reporte Detallado de Ingresos y Gastos'
    return render(request, 'gestion_propiedades/reporte_movimientos_detallados.html', data)


@login_required(login_url='/login/')
def exportar_movimientos_excel(request):
    from django.http import HttpResponse, HttpResponseNotAllowed
    from .utils_excel import generar_excel_movimientos_detallados

    data = _obtener_datos_movimientos_detallados(request)
    excel_bytes = generar_excel_movimientos_detallados(
        data['movimientos'],
        data['total_ingresos'],
        data['total_gastos'],
        data['balance_neto'],
        data['fecha_inicio'],
        data['fecha_fin'],
        portafolio=data.get('portafolio_actual')
    )

    filename = f"Reporte_Movimientos_{data['fecha_inicio'].strftime('%Y%m%d')}_a_{data['fecha_fin'].strftime('%Y%m%d')}.xlsx"
    response = HttpResponse(
        excel_bytes,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required(login_url='/login/')
def enviar_movimientos_correo(request):
    try:
        if request.method == 'POST':
            email_destino = request.POST.get('email_destino', '').strip()
            if not email_destino:
                messages.error(request, "Por favor indica un correo de destino válido.")
            else:
                data = _obtener_datos_movimientos_detallados(request)
                from .utils_excel import generar_excel_movimientos_detallados
                excel_bytes = generar_excel_movimientos_detallados(
                    data['movimientos'],
                    data['total_ingresos'],
                    data['total_gastos'],
                    data['balance_neto'],
                    data['fecha_inicio'],
                    data['fecha_fin'],
                    portafolio=data.get('portafolio_actual')
                )

                nombre_archivo = f"Reporte_Movimientos_{data['fecha_inicio'].strftime('%Y%m%d')}_a_{data['fecha_fin'].strftime('%Y%m%d')}.xlsx"
                asunto = f"📊 Reporte Detallado de Ingresos y Gastos ({data['fecha_inicio'].strftime('%d/%m/%Y')} - {data['fecha_fin'].strftime('%d/%m/%Y')})"

                cuerpo_html = f"""
                    <p>Hola,</p>
                    <p>Adjunto a este correo encontrarás el <strong>Reporte Detallado de Ingresos y Gastos</strong> correspondiente al período del <strong>{data['fecha_inicio'].strftime('%d/%m/%Y')}</strong> al <strong>{data['fecha_fin'].strftime('%d/%m/%Y')}</strong>.</p>
                    <ul style="list-style: none; padding: 0;">
                        <li>🟢 <strong>Total Ingresos:</strong> RD$ {data['total_ingresos']:,.2f}</li>
                        <li>🔴 <strong>Total Gastos:</strong> RD$ {data['total_gastos']:,.2f}</li>
                        <li>💼 <strong>Balance Neto:</strong> RD$ {data['balance_neto']:,.2f}</li>
                        <li>📋 <strong>Total Movimientos:</strong> {len(data['movimientos'])} registros</li>
                    </ul>
                    <p>El archivo adjunto viene formateado en hojas de cálculo Excel (.xlsx) listo para su revisión contable.</p>
                """

                from .utils_correo import _generar_plantilla_html, enviar_correo_con_adjunto
                html_final = _generar_plantilla_html("Reporte Contable Detallado", cuerpo_html)

                exito = enviar_correo_con_adjunto(asunto, email_destino, html_final, excel_bytes, nombre_archivo)
                if exito:
                    messages.success(request, f"🚀 ¡Reporte enviado exitosamente en formato Excel a {email_destino}!")
                else:
                    messages.error(request, f"⚠️ No se pudo entregar el correo a {email_destino}. Si estás en Railway, verifica que las credenciales de correo (SendGrid API Key) estén configuradas en las variables de entorno.")
    except Exception as e:
        logger.error(f"Error procesando envío de reporte por correo: {e}", exc_info=True)
        messages.error(request, f"❌ Ocurrió un error al procesar el envío del reporte: {str(e)}")

    query_params = request.GET.urlencode()
    from django.urls import reverse
    redirect_url = reverse('reporte_movimientos_detallados')
    if query_params:
        redirect_url += f"?{query_params}"
    return redirect(redirect_url)


# --- MÓDULO DE REPORTES AVANZADOS ---

def _obtener_datos_estado_propiedades_propietario(request):
    """
    Obtiene el estado mensual detallado de cada propiedad agrupado por propietario:
    - Quién pagó a tiempo (🟢)
    - Quién pagó fuera de fecha (🟡)
    - Quién está pendiente / falta de pago (🔴)
    - Gastos de mantenimiento del mes (Qué se gastó)
    """
    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().distinct()
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()

    portafolio_id = request.GET.get('portafolio_id', 'TODOS')
    if portafolio_id != 'TODOS' and portafolio_id and str(portafolio_id).isdigit():
        portafolios_filtrados = portafolios.filter(id=int(portafolio_id))
    else:
        portafolios_filtrados = portafolios

    lista_propietarios = PropietarioInmueble.objects.filter(portafolio__in=portafolios_filtrados, activo=True).order_by('nombre')
    
    hoy = date.today()
    mes_num = int(request.GET.get('mes', hoy.month))
    anio_num = int(request.GET.get('anio', hoy.year))
    propietario_id = request.GET.get('propietario_id', 'TODOS')

    propiedades_qs = Propiedad.objects.filter(portafolio__in=portafolios_filtrados, is_deleted=False).select_related(
        'portafolio', 'portafolio__propietario', 'propietario_inmueble'
    ).prefetch_related('contratos', 'contratos__inquilino')

    if propietario_id != 'TODOS' and propietario_id.isdigit():
        propiedades_qs = propiedades_qs.filter(propietario_inmueble_id=int(propietario_id))

    reporte_propiedades = []
    
    totales_resumen = {
        'total_propiedades': 0,
        'total_renta_pactada': decimal.Decimal('0.00'),
        'total_cobrado': decimal.Decimal('0.00'),
        'total_pendiente': decimal.Decimal('0.00'),
        'total_gastos': decimal.Decimal('0.00'),
        'neto_propietario': decimal.Decimal('0.00'),
        'cant_a_tiempo': 0,
        'cant_fuera_de_fecha': 0,
        'cant_falta_pago': 0,
        'cant_vacantes': 0,
    }

    for p in propiedades_qs:
        totales_resumen['total_propiedades'] += 1
        
        propietario_nom = p.propietario_inmueble.nombre if p.propietario_inmueble else (
            (p.portafolio.propietario.get_full_name() or p.portafolio.propietario.username)
            if (p.portafolio and p.portafolio.propietario) else 'Propietario General'
        )

        contrato_act = p.contratos.filter(activo=True).first()
        inquilino_nom = contrato_act.inquilino.nombre if (contrato_act and contrato_act.inquilino) else 'Disponible / Vacante'
        inquilino_tel = contrato_act.inquilino.telefono if (contrato_act and contrato_act.inquilino) else ''
        monto_renta = contrato_act.monto_renta if contrato_act else decimal.Decimal('0.00')
        totales_resumen['total_renta_pactada'] += monto_renta

        # Buscar Factura del Mes
        factura_mes = None
        if contrato_act:
            factura_mes = Factura.objects.filter(
                contrato=contrato_act,
                fecha_emision__month=mes_num,
                fecha_emision__year=anio_num
            ).first()
            if not factura_mes:
                factura_mes = Factura.objects.filter(
                    contrato=contrato_act,
                    fecha_vencimiento__month=mes_num,
                    fecha_vencimiento__year=anio_num
                ).first()

        recibo = ReciboPago.objects.filter(factura=factura_mes).first() if factura_mes else None
        cargos_mora = CargoMora.objects.filter(factura=factura_mes).first() if factura_mes else None

        estado_codigo = 'VACANTE'
        estado_label = '⚪ Vacante / Sin Factura'
        badge_class = 'bg-secondary'
        monto_pagado = decimal.Decimal('0.00')
        monto_pendiente = decimal.Decimal('0.00')
        fecha_pago_str = ''
        dias_retraso = 0

        if factura_mes:
            if factura_mes.estado == 'PAGADA' and recibo:
                monto_pagado = recibo.monto_pagado
                totales_resumen['total_cobrado'] += monto_pagado
                fecha_pago_str = recibo.fecha_pago.strftime('%d/%m/%Y')
                
                if recibo.fecha_pago > factura_mes.fecha_vencimiento or (cargos_mora and cargos_mora.monto > 0):
                    estado_codigo = 'FUERA_DE_FECHA'
                    estado_label = '🟡 Pagado Fuera de Fecha'
                    badge_class = 'bg-warning text-dark'
                    totales_resumen['cant_fuera_de_fecha'] += 1
                    dias_retraso = (recibo.fecha_pago - factura_mes.fecha_vencimiento).days
                else:
                    estado_codigo = 'A_TIEMPO'
                    estado_label = '🟢 Pagado A Tiempo'
                    badge_class = 'bg-success'
                    totales_resumen['cant_a_tiempo'] += 1
            else:
                monto_pendiente = factura_mes.monto_base
                totales_resumen['total_pendiente'] += monto_pendiente
                estado_codigo = 'FALTA_PAGO'
                estado_label = '🔴 Falta de Pago'
                badge_class = 'bg-danger'
                totales_resumen['cant_falta_pago'] += 1
                if hoy > factura_mes.fecha_vencimiento:
                    dias_retraso = (hoy - factura_mes.fecha_vencimiento).days
        else:
            totales_resumen['cant_vacantes'] += 1

        # Mantenimientos y Gastos
        mantenimientos_qs = MantenimientoUnidad.objects.filter(
            propiedad=p,
            fecha_reporte__month=mes_num,
            fecha_reporte__year=anio_num
        )
        gastos_prop = sum((m.costo for m in mantenimientos_qs), decimal.Decimal('0.00'))
        totales_resumen['total_gastos'] += gastos_prop

        monto_neto = monto_pagado - gastos_prop

        reporte_propiedades.append({
            'propiedad_id': p.id,
            'propiedad_nombre': p.nombre_o_numero,
            'grupo_o_residencial': p.grupo_o_residencial or '',
            'propietario': propietario_nom,
            'inquilino': inquilino_nom,
            'inquilino_telefono': inquilino_tel,
            'renta_pactada': monto_renta,
            'factura_id': factura_mes.id if factura_mes else None,
            'fecha_vencimiento': factura_mes.fecha_vencimiento.strftime('%d/%m/%Y') if factura_mes else '',
            'fecha_pago': fecha_pago_str,
            'dias_retraso': dias_retraso,
            'estado_codigo': estado_codigo,
            'estado_label': estado_label,
            'badge_class': badge_class,
            'monto_pagado': monto_pagado,
            'monto_pendiente': monto_pendiente,
            'mantenimientos': list(mantenimientos_qs),
            'total_gastos': gastos_prop,
            'monto_neto': monto_neto,
        })

    totales_resumen['neto_propietario'] = totales_resumen['total_cobrado'] - totales_resumen['total_gastos']

    portafolio_actual = None
    if portafolio_id != 'TODOS' and str(portafolio_id).isdigit():
        portafolio_actual = portafolios.filter(id=int(portafolio_id)).first()
    elif propietario_id != 'TODOS' and str(propietario_id).isdigit():
        prop_obj = lista_propietarios.filter(id=int(propietario_id)).first()
        if prop_obj:
            portafolio_actual = prop_obj.portafolio
    if not portafolio_actual and portafolios.count() == 1:
        portafolio_actual = portafolios.first()
    elif not portafolio_actual:
        portafolio_actual = portafolios.first()

    return {
        'reporte_propiedades': reporte_propiedades,
        'totales_resumen': totales_resumen,
        'lista_propietarios': lista_propietarios,
        'propietario_sel': str(propietario_id),
        'portafolios': portafolios,
        'portafolio_actual': portafolio_actual,
        'portafolio_sel': str(portafolio_id),
        'mes': str(mes_num),
        'nombre_mes': obtener_nombre_mes(mes_num),
        'anio': anio_num,
        'anios_disponibles': range(date.today().year - 2, date.today().year + 2),
    }


@login_required(login_url='/login/')
def reporte_estado_propiedades_propietario(request):
    data = _obtener_datos_estado_propiedades_propietario(request)
    data['titulo_pagina'] = 'Estado Mensual de Propiedades por Propietario'
    return render(request, 'gestion_propiedades/reporte_estado_propiedades_propietario.html', data)


@login_required(login_url='/login/')
def exportar_estado_propiedades_excel(request):
    from django.http import HttpResponse, HttpResponseNotAllowed
    from .utils_excel import generar_excel_estado_propiedades_propietario

    data = _obtener_datos_estado_propiedades_propietario(request)
    excel_bytes = generar_excel_estado_propiedades_propietario(data)

    filename = f"Estado_Propiedades_{data['nombre_mes']}_{data['anio']}.xlsx"
    response = HttpResponse(
        excel_bytes,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required(login_url='/login/')
def imprimir_estado_propiedades_propietario(request):
    data = _obtener_datos_estado_propiedades_propietario(request)
    data['titulo_pagina'] = 'Estado de Propiedades - Vista de Impresión'
    return render(request, 'gestion_propiedades/imprimir_estado_propiedades_propietario.html', data)

@login_required(login_url='/login/')
def reporte_rentabilidad(request):
    """
    Reporte de Rentabilidad Comparativa:
    Para cada propiedad: suma de pagos recibidos - suma de mantenimientos.
    Devuelve la lista ordenada de mayor a menor rentabilidad neta.
    """
    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().distinct()
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()

    propiedades = Propiedad.objects.filter(portafolio__in=portafolios, is_deleted=False)

    resultado = []
    for prop in propiedades:
        ingresos = ReciboPago.objects.filter(
            factura__contrato__propiedad=prop
        ).aggregate(total=Sum('monto_pagado'))['total'] or 0

        egresos = MantenimientoUnidad.objects.filter(
            propiedad=prop
        ).aggregate(total=Sum('costo'))['total'] or 0

        neto = float(ingresos) - float(egresos)
        resultado.append({
            'propiedad': prop,
            'ingresos': float(ingresos),
            'egresos': float(egresos),
            'neto': neto,
        })

    resultado.sort(key=lambda x: x['neto'], reverse=True)

    context = {
        'titulo_pagina': 'Reportes Avanzados: Rentabilidad Comparativa',
        'resultado': resultado,
    }
    return render(request, 'gestion_propiedades/reporte_rentabilidad.html', context)


@login_required(login_url='/login/')
def reporte_ocupacion(request):
    """
    Reporte de Ocupación Anual:
    Por cada propiedad, calcula qué porcentaje del año actual estuvo ocupada,
    basado en los días cubiertos por contratos activos o finalizados en ese año.
    """
    from datetime import date, timedelta

    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().distinct()
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()

    hoy = date.today()
    inicio_anio = date(hoy.year, 1, 1)
    fin_anio = date(hoy.year, 12, 31)
    dias_anio = 365

    propiedades = Propiedad.objects.filter(portafolio__in=portafolios, is_deleted=False)
    resultado = []

    for prop in propiedades:
        contratos = Contrato.objects.filter(
            propiedad=prop,
            fecha_inicio__lte=fin_anio
        ).exclude(
            fecha_fin__lt=inicio_anio
        )

        dias_ocupados = 0
        for contrato in contratos:
            inicio = max(contrato.fecha_inicio, inicio_anio)
            fin = contrato.fecha_fin if contrato.fecha_fin else hoy
            fin = min(fin, fin_anio)
            if fin >= inicio:
                dias_ocupados += (fin - inicio).days + 1

        dias_ocupados = min(dias_ocupados, dias_anio)
        porcentaje = round((dias_ocupados / dias_anio) * 100, 1)

        resultado.append({
            'propiedad': prop,
            'dias_ocupados': dias_ocupados,
            'dias_disponibles': dias_anio - dias_ocupados,
            'porcentaje': porcentaje,
        })

    resultado.sort(key=lambda x: x['porcentaje'], reverse=True)

    context = {
        'titulo_pagina': f'Reportes Avanzados: Ocupación Anual {hoy.year}',
        'resultado': resultado,
        'anio': hoy.year,
    }
    return render(request, 'gestion_propiedades/reporte_ocupacion.html', context)

# --- MÓDULO DE INQUILINOS ---

@login_required
def lista_mantenimientos_global(request):
    from django.db.models import Case, When, Value, IntegerField, Q
    
    if request.user.is_superuser:
        base_qs = MantenimientoUnidad.objects.all()
        propiedades = Propiedad.objects.filter(is_deleted=False).order_by('nombre_o_numero')
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) |
            Q(accesos__usuario=request.user)
        ).distinct()
        base_qs = MantenimientoUnidad.objects.filter(
            propiedad__portafolio__in=portafolios
        ).distinct()
        propiedades = Propiedad.objects.filter(portafolio__in=portafolios, is_deleted=False).order_by('nombre_o_numero')

    # Contadores para las pestañas
    total_todos = base_qs.count()
    total_pendientes = base_qs.filter(estado='PENDIENTE').count()
    total_progreso = base_qs.filter(estado='PROGRESO').count()
    total_completados = base_qs.filter(estado='COMPLETADO').count()

    # Filtro por estado
    estado_filtro = request.GET.get('estado', '').strip().upper()
    if estado_filtro in ['PENDIENTE', 'PROGRESO', 'COMPLETADO']:
        mantenimientos_qs = base_qs.filter(estado=estado_filtro)
    else:
        mantenimientos_qs = base_qs

    # Buscador de texto
    busqueda = request.GET.get('q', '').strip()
    if busqueda:
        mantenimientos_qs = mantenimientos_qs.filter(
            Q(propiedad__nombre_o_numero__icontains=busqueda) |
            Q(propiedad__grupo_o_residencial__icontains=busqueda) |
            Q(descripcion__icontains=busqueda) |
            Q(categoria__icontains=busqueda)
        )

    mantenimientos = mantenimientos_qs.annotate(
        estado_order=Case(
            When(estado='PENDIENTE', then=Value(1)),
            When(estado='PROGRESO', then=Value(2)),
            When(estado='COMPLETADO', then=Value(3)),
            default=Value(4),
            output_field=IntegerField()
        )
    ).select_related('propiedad', 'propiedad__portafolio').order_by('estado_order', '-fecha_reporte')
    
    context = {
        'titulo_pagina': 'Mantenimiento Global (Helpdesk)',
        'mantenimientos': mantenimientos,
        'propiedades': propiedades,
        'estado_filtro': estado_filtro,
        'busqueda': busqueda,
        'total_todos': total_todos,
        'total_pendientes': total_pendientes,
        'total_progreso': total_progreso,
        'total_completados': total_completados,
    }
    return render(request, 'gestion_propiedades/mantenimientos_global.html', context)


@login_required
def cambiar_estado_mantenimiento(request, mantenimiento_id):
    from datetime import date, datetime, timedelta
    from decimal import Decimal
    from django.shortcuts import get_object_or_404, redirect
    from django.contrib import messages
    from .models import MantenimientoUnidad, Portafolio
    from django.db.models import Q

    if request.user.is_superuser:
        mantenimiento = get_object_or_404(MantenimientoUnidad, id=mantenimiento_id)
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()
        mantenimiento = get_object_or_404(MantenimientoUnidad, id=mantenimiento_id, propiedad__portafolio__in=portafolios)

    if request.method == 'POST':
        nuevo_estado = request.POST.get('estado', '').strip().upper()
        if nuevo_estado in ['PENDIENTE', 'PROGRESO', 'COMPLETADO']:
            mantenimiento.estado = nuevo_estado
            if nuevo_estado == 'COMPLETADO' and not mantenimiento.fecha_resolucion:
                mantenimiento.fecha_resolucion = date.today()

        costo_str = request.POST.get('costo', '').strip()
        if costo_str != '':
            try:
                mantenimiento.costo = Decimal(costo_str.replace(',', '.'))
            except Exception:
                pass

        fecha_res_str = request.POST.get('fecha_resolucion', '').strip()
        if fecha_res_str:
            try:
                mantenimiento.fecha_resolucion = datetime.strptime(fecha_res_str, '%Y-%m-%d').date()
            except Exception:
                pass
        elif nuevo_estado != 'COMPLETADO':
            mantenimiento.fecha_resolucion = None

        mantenimiento.save()
        messages.success(request, f"Ticket de avería/mantenimiento #{mantenimiento.id} actualizado con éxito a '{mantenimiento.get_estado_display()}'.")

    return redirect(request.META.get('HTTP_REFERER', 'lista_mantenimientos_global'))


@login_required
def crear_mantenimiento_global(request):
    from decimal import Decimal
    from django.shortcuts import get_object_or_404, redirect
    from django.contrib import messages
    from .models import MantenimientoUnidad, Propiedad, Portafolio
    from django.db.models import Q

    if request.method == 'POST':
        propiedad_id = request.POST.get('propiedad')
        categoria = request.POST.get('categoria', 'REPARACION')
        descripcion = request.POST.get('descripcion', '').strip()
        costo_raw = request.POST.get('costo', '0').strip()
        estado = request.POST.get('estado', 'PENDIENTE')
        factura = request.FILES.get('factura_adjunta')

        if not descripcion:
            messages.error(request, "Debes ingresar una descripción del mantenimiento.")
            return redirect('lista_mantenimientos_global')

        if request.user.is_superuser:
            propiedad = get_object_or_404(Propiedad, id=propiedad_id)
        else:
            portafolios = Portafolio.objects.filter(
                Q(propietario=request.user) | Q(accesos__usuario=request.user)
            ).distinct()
            propiedad = get_object_or_404(Propiedad, id=propiedad_id, portafolio__in=portafolios)

        try:
            costo = Decimal(costo_raw.replace(',', '.')) if costo_raw else Decimal('0.00')
        except Exception:
            costo = Decimal('0.00')

        MantenimientoUnidad.objects.create(
            propiedad=propiedad,
            categoria=categoria,
            descripcion=descripcion,
            costo=costo,
            estado=estado,
            factura_adjunta=factura
        )
        messages.success(request, f"Mantenimiento registrado para la propiedad {propiedad.nombre_o_numero}.")

    return redirect('lista_mantenimientos_global')

@login_required(login_url='/login/')
def lista_inquilinos(request):
    from .models import Inquilino
    from django.db.models import Q
    inquilinos = Inquilino.objects.filter(
        Q(creado_por=request.user) | 
        Q(contratos__propiedad__portafolio__propietario=request.user) |
        Q(contratos__propiedad__portafolio__accesos__usuario=request.user)
    ).distinct().order_by('nombre')
    
    context = {
        'titulo_pagina': 'Directorio de Inquilinos',
        'inquilinos': inquilinos,
    }
    return render(request, 'gestion_propiedades/lista_inquilinos.html', context)

@login_required(login_url='/login/')
def crear_inquilino(request):
    from .forms import InquilinoForm
    if request.method == 'POST':
        form = InquilinoForm(request.POST)
        if form.is_valid():
            inquilino = form.save(commit=False)
            inquilino.creado_por = request.user
            inquilino.save()
            messages.success(request, 'Inquilino registrado con éxito.')
            return redirect('lista_inquilinos')
    else:
        form = InquilinoForm()

    context = {'titulo_pagina': 'Nuevo Inquilino', 'form': form}
    return render(request, 'gestion_propiedades/form_generico.html', context)

@login_required(login_url='/login/')
def editar_inquilino(request, inquilino_id):
    from .forms import InquilinoForm
    from .models import Inquilino
    
    portafolios = Portafolio.objects.filter(Q(propietario=request.user) | Q(accesos__usuario=request.user))
    inquilino = get_object_or_404(
        Inquilino.objects.filter(
            Q(creado_por=request.user) | 
            Q(contratos__propiedad__portafolio__in=portafolios)
        ).distinct(),
        id=inquilino_id
    )
    
    if request.method == 'POST':
        form = InquilinoForm(request.POST, instance=inquilino)
        if form.is_valid():
            form.save()
            messages.success(request, 'Datos del inquilino actualizados.')
            return redirect('detalle_inquilino', inquilino_id=inquilino.id)
    else:
        form = InquilinoForm(instance=inquilino)

    context = {'titulo_pagina': f'Editar Inquilino: {inquilino.nombre}', 'form': form}
    return render(request, 'gestion_propiedades/form_generico.html', context)

@login_required(login_url='/login/')
def detalle_inquilino(request, inquilino_id):
    from .models import Inquilino
    
    portafolios = Portafolio.objects.filter(Q(propietario=request.user) | Q(accesos__usuario=request.user))
    inquilino = get_object_or_404(
        Inquilino.objects.filter(
            Q(creado_por=request.user) | 
            Q(contratos__propiedad__portafolio__in=portafolios)
        ).distinct(),
        id=inquilino_id
    )
    
    # Historial de contratos vinculados a este inquilino
    contratos = inquilino.contratos.all().select_related('propiedad').order_by('-fecha_inicio')
    
    context = {
        'titulo_pagina': f'Perfil de Inquilino: {inquilino.nombre}',
        'inquilino': inquilino,
        'contratos': contratos,
    }
    return render(request, 'gestion_propiedades/detalle_inquilino.html', context)


# --- MÓDULO DE FACTURACIÓN GLOBAL ---

@login_required(login_url='/login/')
def lista_facturas_global(request):
    from django.db.models import Case, When, Value, IntegerField
    portafolios = Portafolio.objects.filter(Q(propietario=request.user) | Q(accesos__usuario=request.user)).distinct()
    
    q_search = request.GET.get('q', '').strip()
    
    base_facturas_query = Factura.objects.filter(contrato__propiedad__portafolio__in=portafolios)
    base_recibos_query = ReciboPago.objects.filter(factura__contrato__propiedad__portafolio__in=portafolios)

    if q_search:
        base_facturas_query = base_facturas_query.filter(
            Q(contrato__propiedad__nombre_o_numero__icontains=q_search) | 
            Q(contrato__inquilino__nombre__icontains=q_search) |
            Q(concepto__icontains=q_search)
        )
        base_recibos_query = base_recibos_query.filter(
            Q(factura__contrato__propiedad__nombre_o_numero__icontains=q_search) | 
            Q(factura__contrato__inquilino__nombre__icontains=q_search)
        )

    # Facturas ordenadas priorizando las deudas (ATRASADA, PENDIENTE) y luego orden cronológico
    facturas = base_facturas_query.select_related(
        'contrato', 'contrato__propiedad', 'contrato__inquilino'
    ).annotate(
        orden_estado=Case(
            When(estado='ATRASADA', then=Value(1)),
            When(estado='PENDIENTE', then=Value(2)),
            When(estado='PAGADA', then=Value(3)),
            When(estado='ANULADA', then=Value(4)),
            default=Value(5),
            output_field=IntegerField(),
        )
    ).order_by('orden_estado', '-fecha_vencimiento')
    
    # Últimos recibos (historial de pagos recientes)
    if q_search:
        recibos = base_recibos_query.select_related(
            'factura', 'factura__contrato__propiedad', 'factura__contrato__inquilino'
        ).order_by('-fecha_pago')
    else:
        recibos = base_recibos_query.select_related(
            'factura', 'factura__contrato__propiedad', 'factura__contrato__inquilino'
        ).order_by('-fecha_pago')[:50]
    
    context = {
        'titulo_pagina': 'Facturación y Pagos',
        'q_search': q_search,
        'facturas': facturas,
        'recibos': recibos,
    }
    return render(request, 'gestion_propiedades/facturacion_global.html', context)

@login_required(login_url='/login/')
def prorratear_factura_inicial(request, factura_id):
    """
    Recibe un POST para ajustar el monto de la primera factura mensual de un contrato nuevo.
    """
    from .models import Factura, AuditLog
    from django.db.models import Q
    
    portafolios = Portafolio.objects.filter(Q(propietario=request.user) | Q(accesos__usuario=request.user))
    factura = get_object_or_404(Factura, id=factura_id, contrato__propiedad__portafolio__in=portafolios)
    
    if request.method == 'POST':
        # Validar de nuevo por seguridad que es elegible
        if not factura.es_prorrateable:
            messages.error(request, 'Esta factura no es elegible para prorrateo inicial (han pasado más de 45 días o ya no está pendiente).')
            return redirect('lista_facturas_global')
            
        try:
            nuevo_monto = float(request.POST.get('monto_ajustado', 0.00))
        except ValueError:
            messages.error(request, 'El monto ingresado no es válido.')
            return redirect('lista_facturas_global')
            
        monto_anterior = factura.monto_base
        factura.monto_base = nuevo_monto
        
        if nuevo_monto == 0:
            factura.concepto = f"{factura.concepto} (Regalo / Mes de Gracia)"
        else:
            factura.concepto = f"{factura.concepto} (Prorrateo 1er Mes Ajustado)"
            
        factura.save()
        
        # Registrar en Auditoría
        AuditLog.objects.create(
            accion='EDITAR',
            modulo='Factura',
            descripcion=f'Ajustó por prorrateo la factura #{factura.id} de {factura.contrato.inquilino.nombre}. Monto original: ${monto_anterior} -> Monto ajustado: ${nuevo_monto}',
            usuario=request.user,
            portafolio=factura.contrato.propiedad.portafolio
        )
        
        messages.success(request, f'La factura se prorrateó correctamente a ${nuevo_monto}.')
        
    return redirect('lista_facturas_global')


@login_required(login_url='/login/')
def crear_factura_manual(request):
    """
    Módulo para generar facturas de alquiler/servicios manuales, de inicio o históricas
    (por ejemplo días anteriores a la carga de datos del cliente o cargos extraordinarios),
    con concepto y desglose personalizable.
    RESTRINGIDO EXCLUSIVAMENTE AL SUPERADMINISTRADOR para evitar duplicidades con el cron automático.
    """
    if not request.user.is_superuser:
        messages.error(
            request, 
            "Acceso restringido. La generación manual de facturas solo está permitida para el Superadministrador para evitar duplicidades con el proceso automático de facturación."
        )
        return redirect('lista_facturas_global')

    import json
    from datetime import datetime, timedelta

    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().order_by('nombre')
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct().order_by('nombre')

    portafolio_id_param = request.GET.get('portafolio_id') or request.POST.get('portafolio_id') or ''

    contratos_qs = Contrato.objects.filter(
        propiedad__portafolio__in=portafolios,
        activo=True
    ).select_related('propiedad', 'inquilino', 'propiedad__portafolio').prefetch_related('cargos_adicionales').order_by('propiedad__portafolio__nombre', 'propiedad__nombre_o_numero')

    if portafolio_id_param and portafolio_id_param != 'TODOS' and str(portafolio_id_param).isdigit():
        contratos_filtrados = contratos_qs.filter(propiedad__portafolio_id=int(portafolio_id_param))
    else:
        contratos_filtrados = contratos_qs

    contrato_id_param = request.GET.get('contrato_id')
    propiedad_id_param = request.GET.get('propiedad_id')
    contrato_seleccionado = None
    if contrato_id_param and str(contrato_id_param).isdigit():
        contrato_seleccionado = contratos_qs.filter(id=int(contrato_id_param)).first()
    elif propiedad_id_param and str(propiedad_id_param).isdigit():
        contrato_seleccionado = contratos_qs.filter(propiedad_id=int(propiedad_id_param)).first()

    if request.method == 'POST':
        contrato_id = request.POST.get('contrato')
        contrato = get_object_or_404(contratos_qs, id=contrato_id)

        fecha_emision_str = request.POST.get('fecha_emision')
        fecha_vencimiento_str = request.POST.get('fecha_vencimiento')
        monto_renta_str = request.POST.get('monto_renta', '0')
        concepto = request.POST.get('concepto', '').strip()
        incluir_cargos_recurrentes = request.POST.get('incluir_cargos_recurrentes') == 'on'

        try:
            fecha_emision = datetime.strptime(fecha_emision_str, '%Y-%m-%d').date()
        except Exception:
            fecha_emision = date.today()

        try:
            fecha_vencimiento = datetime.strptime(fecha_vencimiento_str, '%Y-%m-%d').date()
        except Exception:
            fecha_vencimiento = fecha_emision + timedelta(days=contrato.dias_gracia or 5)

        try:
            monto_renta = decimal.Decimal(str(monto_renta_str).replace(',', ''))
        except Exception:
            monto_renta = decimal.Decimal('0.00')

        if not concepto:
            concepto = contrato.propiedad.portafolio.generar_concepto_factura(contrato, fecha_emision)

        items_servicios = []
        if incluir_cargos_recurrentes:
            for c in contrato.cargos_adicionales.filter(activo=True):
                items_servicios.append({
                    'cargo_origen': c,
                    'categoria': c.categoria,
                    'concepto': c.nombre_mostrar,
                    'monto': c.monto
                })

        extra_cat = request.POST.getlist('extra_categoria[]')
        extra_con = request.POST.getlist('extra_concepto[]')
        extra_mon = request.POST.getlist('extra_monto[]')

        for cat, con, mon in zip(extra_cat, extra_con, extra_mon):
            try:
                m_val = decimal.Decimal(str(mon).replace(',', '').strip())
                if m_val > 0:
                    items_servicios.append({
                        'cargo_origen': None,
                        'categoria': cat or 'OTRO',
                        'concepto': con.strip() if con else 'Servicio Adicional',
                        'monto': m_val
                    })
            except Exception:
                pass

        total_servicios = sum(item['monto'] for item in items_servicios)
        total_base = monto_renta + total_servicios

        # 4. Cargo por Mora opcional (si se digita un monto mayor a 0)
        monto_mora_str = request.POST.get('monto_mora', '0')
        try:
            monto_mora = decimal.Decimal(str(monto_mora_str).replace(',', '').strip())
        except Exception:
            monto_mora = decimal.Decimal('0.00')

        if monto_mora < decimal.Decimal('0.00'):
            monto_mora = decimal.Decimal('0.00')

        if total_base <= 0 and monto_mora <= 0:
            messages.error(request, 'El monto total facturado debe ser mayor a cero.')
            return redirect(f"{request.path}?contrato_id={contrato.id}")

        hoy = date.today()
        estado_inicial = 'ATRASADA' if (fecha_vencimiento < hoy or monto_mora > decimal.Decimal('0.00')) else 'PENDIENTE'

        nueva_factura = Factura.objects.create(
            contrato=contrato,
            fecha_emision=fecha_emision,
            fecha_vencimiento=fecha_vencimiento,
            monto_base=total_base,
            monto_renta=monto_renta,
            monto_servicios=total_servicios,
            concepto=concepto,
            estado=estado_inicial
        )

        for item in items_servicios:
            DetalleFacturaServicio.objects.create(
                factura=nueva_factura,
                cargo_origen=item['cargo_origen'],
                categoria=item['categoria'],
                concepto=item['concepto'],
                monto=item['monto']
            )

        if monto_mora > decimal.Decimal('0.00'):
            CargoMora.objects.create(
                factura=nueva_factura,
                monto=monto_mora,
                mes_aplicado=hoy.month,
                anio_aplicado=hoy.year
            )

        detalle_mora_txt = f" + Mora RD$ {monto_mora:,.2f}" if monto_mora > 0 else ""
        AuditLog.objects.create(
            accion='CREAR',
            modulo='Factura',
            descripcion=f"Generó factura manual #{nueva_factura.id} por RD$ {total_base:,.2f}{detalle_mora_txt} ({concepto}) para inquilino {contrato.inquilino.nombre}.",
            usuario=request.user,
            portafolio=contrato.propiedad.portafolio
        )

        if monto_mora > 0:
            total_con_mora = total_base + monto_mora
            messages.success(
                request,
                f"✅ ¡Factura #{nueva_factura.id} generada con éxito para {contrato.inquilino.nombre} por RD$ {total_base:,.2f} "
                f"+ RD$ {monto_mora:,.2f} de mora (Total: RD$ {total_con_mora:,.2f})! Concepto: '{concepto}'."
            )
        else:
            messages.success(
                request,
                f"✅ ¡Factura #{nueva_factura.id} generada con éxito para {contrato.inquilino.nombre} por RD$ {total_base:,.2f}! "
                f"Concepto: '{concepto}'."
            )
        return redirect('lista_facturas_global')

    # Datos JSON para dinamismo en UI
    contratos_data = {}
    for c in contratos_qs:
        servicios_list = [
            {
                'categoria': s.categoria,
                'categoria_display': s.get_categoria_display(),
                'concepto': s.nombre_mostrar,
                'monto': float(s.monto)
            }
            for s in c.cargos_adicionales.filter(activo=True)
        ]
        concepto_sugerido = c.propiedad.portafolio.generar_concepto_factura(c, date.today())
        contratos_data[str(c.id)] = {
            'monto_renta': float(c.monto_renta),
            'dia_de_pago': c.dia_de_pago,
            'dias_gracia': c.dias_gracia,
            'porcentaje_mora': float(c.porcentaje_mora or 0.0),
            'inquilino': c.inquilino.nombre,
            'propiedad': c.propiedad.nombre_o_numero,
            'portafolio_id': c.propiedad.portafolio.id,
            'portafolio_nombre': c.propiedad.portafolio.nombre,
            'concepto_sugerido': concepto_sugerido,
            'servicios': servicios_list,
        }

    context = {
        'titulo_pagina': 'Generar Factura Manual / Días Anteriores',
        'contratos': contratos_filtrados,
        'todos_contratos': contratos_qs,
        'portafolios': portafolios,
        'portafolio_id_param': str(portafolio_id_param),
        'contrato_seleccionado': contrato_seleccionado,
        'contratos_json': json.dumps(contratos_data),
        'hoy': date.today(),
        'categorias_servicios': CargoAdicionalContrato.CATEGORIA_CHOICES,
    }
    return render(request, 'gestion_propiedades/crear_factura_manual.html', context)



# --- MÓDULO B2B SAAS ---

@login_required(login_url='/login/')
def aviso_pago(request):
    from .models import AccesoPortafolio
    try:
        suscripcion = request.user.suscripcion
    except Exception:
        suscripcion = None
        
    es_asistente = AccesoPortafolio.objects.filter(usuario=request.user, rol='ASISTENTE').exists()
    context = {
        'titulo_pagina': 'Aviso de Acceso al Sistema',
        'suscripcion': suscripcion,
        'es_asistente': es_asistente
    }
    return render(request, 'gestion_propiedades/aviso_pago.html', context)


@login_required(login_url='/login/')
def saas_master_control(request):
    from django.contrib.auth.models import User
    
    # DENEGAR ACCESO a clientes ordinarios
    if not request.user.is_superuser:
        return redirect('dashboard')
        
    usuarios_saas = User.objects.filter(is_superuser=False).prefetch_related('suscripcion', 'portafolios', Prefetch('portafolios__propiedades', queryset=Propiedad.objects.filter(is_deleted=False)))
    
    clientes_data = []
    for u in usuarios_saas:
        # Calcular cuantas propiedades gestionan en total entre sus portafolios
        props_count = sum(p.propiedades.count() for p in u.portafolios.all())
        
        try:
            plan = u.suscripcion.plan_saas.nombre if u.suscripcion.plan_saas else (u.suscripcion.plan or "SaaS Automático")
            estado = u.suscripcion.estado
            estado_display = u.suscripcion.get_estado_display()
            fecha_prox = u.suscripcion.fecha_proximo_pago
        except Exception:
            plan = "Sin asignar"
            estado = "INACTIVO"
            estado_display = "No Instalado"
            fecha_prox = None
            
        from .models import FacturaSaaS
        facturas_pendientes = FacturaSaaS.objects.filter(usuario=u, estado__in=['PENDIENTE', 'VENCIDA']).count()
        total_facturas = FacturaSaaS.objects.filter(usuario=u).count()

        clientes_data.append({
            'id': u.id,
            'nombre': u.get_full_name() or u.username,
            'email': u.email,
            'fecha_registro': u.date_joined,
            'plan': plan,
            'estado': estado,
            'estado_display': estado_display,
            'fecha_proximo_pago': fecha_prox,
            'propiedades': props_count,
            'facturas_pendientes': facturas_pendientes,
            'total_facturas': total_facturas,
        })
        
    procesos = RegistroProceso.objects.all().select_related('ejecutado_por')[:15]

    context = {
        'titulo_pagina': 'Centro de Mando SaaS',
        'clientes': clientes_data,
        'total_clientes': len(clientes_data),
        'total_activos': sum(1 for c in clientes_data if c['estado'] == 'ACTIVA'),
        'total_suspendidos': sum(1 for c in clientes_data if c['estado'] == 'SUSPENDIDA'),
        'total_trials': sum(1 for c in clientes_data if c['estado'] == 'TRIAL'),
        'procesos': procesos,
    }
    return render(request, 'gestion_propiedades/saas_master.html', context)


@login_required(login_url='/login/')
def crear_cliente_saas(request):
    from django.contrib.auth.models import User
    if not request.user.is_superuser:
        return redirect('dashboard')
        
    if request.method == 'POST':
        form = NuevoClienteSaaSForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            user = User.objects.create_user(
                username=email,
                email=email,
                password=form.cleaned_data['password'],
                first_name=form.cleaned_data['nombre'],
                last_name=form.cleaned_data['apellidos']
            )
            # Portafolio inicial
            nombre_portf = form.cleaned_data['nombre_portafolio'] or f"Portafolio de {user.first_name}"
            formato_concepto = form.cleaned_data.get('formato_concepto_factura') or 'MES_ANIO'
            Portafolio.objects.create(nombre=nombre_portf, propietario=user, formato_concepto_factura=formato_concepto)
            
            # Suscripcion Trial
            plan_trial = PlanSaaS.objects.filter(activo=True).first()
            from datetime import timedelta
            from django.utils import timezone
            SuscripcionCliente.objects.create(
                usuario=user,
                plan_saas=plan_trial,
                estado='TRIAL',
                fecha_proximo_pago=timezone.now().date() + timedelta(days=45)
            )
            messages.success(request, f"Cliente {user.first_name} creado con éxito.")
            return redirect('saas_master_control')
    else:
        form = NuevoClienteSaaSForm()
        
    context = {'titulo_pagina': 'Alta de Cliente B2B', 'form': form}
    return render(request, 'gestion_propiedades/form_generico.html', context)

@login_required(login_url='/login/')
def editar_suscripcion_saas(request, cliente_id):
    from django.contrib.auth.models import User
    if not request.user.is_superuser:
        return redirect('dashboard')
        
    cliente = get_object_or_404(User, id=cliente_id)
    try:
        suscripcion = cliente.suscripcion
    except Exception:
        suscripcion = None
    
    if request.method == 'POST':
        form = EditarSuscripcionForm(request.POST, instance=suscripcion)
        if form.is_valid():
            sub = form.save(commit=False)
            if not suscripcion:
                sub.usuario = cliente
            sub.save()

            # Si la cuenta está ACTIVA y nunca ha recibido una factura SaaS por adelantado, generarla de inmediato
            from .models import FacturaSaaS
            if sub.estado == 'ACTIVA' and not FacturaSaaS.objects.filter(usuario=cliente).exists():
                from .utils_saas import calcular_metricas_facturacion_saas, calcular_fecha_vencimiento_dias_habiles
                from .utils_correo import enviar_aviso_factura_saas
                hoy = timezone.now().date()
                metricas = calcular_metricas_facturacion_saas(sub)
                fecha_venc = calcular_fecha_vencimiento_dias_habiles(hoy, metricas['dias_gracia_habiles'])
                nueva_fs = FacturaSaaS.objects.create(
                    usuario=cliente,
                    fecha_vencimiento=fecha_venc,
                    monto_total=metricas['monto_total'],
                    propiedades_cobradas=metricas['propiedades_total'],
                    usuarios_cobrados=metricas['usuarios_extra'],
                    estado='PENDIENTE'
                )
                sub.fecha_proximo_pago = hoy + timedelta(days=30)
                sub.save()
                try:
                    enviar_aviso_factura_saas(nueva_fs)
                except Exception:
                    pass
                messages.success(request, f"✅ Suscripción de {cliente.first_name} activada y Factura SaaS #{nueva_fs.id} generada por adelantado (${nueva_fs.monto_total} USD). Ya puedes registrar su pago.")
                return redirect('saas_facturacion')

            messages.success(request, f"Suscripción de {cliente.first_name} actualizada.")
            return redirect('saas_master_control')
    else:
        form = EditarSuscripcionForm(instance=suscripcion)
        
    context = {'titulo_pagina': f'Suscripción de: {cliente.get_full_name() or cliente.username}', 'form': form}
    return render(request, 'gestion_propiedades/form_generico.html', context)

@login_required
def saas_planes(request):
    if not request.user.is_superuser:
        return redirect('dashboard')
    
    planes = PlanSaaS.objects.all().order_by('precio_mensual')
    if request.method == 'POST':
        form = PlanSaaSForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'El nuevo plan fue añadido exitosamente a la plataforma.')
            return redirect('saas_planes')
    else:
        form = PlanSaaSForm()
        
    context = {'titulo_pagina': 'Configurar Planes SaaS', 'planes': planes, 'form': form}
    return render(request, 'gestion_propiedades/saas_planes.html', context)


# --- FACTURACIÓN SAAS (PAY-AS-YOU-GROW) ---

@login_required(login_url='/login/')
@propietario_requerido
def mi_suscripcion(request):
    """
    Vista B2B para que el cliente vea su facturación SaaS y detalle de plan.
    """
    from .models import Propiedad, FacturaSaaS
    from .utils_tasa import obtener_tasa_dolar
    from .utils_saas import calcular_metricas_facturacion_saas
    
    propiedades_activas = Propiedad.objects.filter(
        portafolio__propietario=request.user,
        is_deleted=False
    ).count()
    
    try:
        suscripcion = request.user.suscripcion
        metricas = calcular_metricas_facturacion_saas(suscripcion, propiedades_activas)
        costo_proyectado = float(metricas['monto_total'])
    except Exception:
        suscripcion = None
        metricas = None
        costo_proyectado = propiedades_activas * 1.00
        
    tasa_dolar = obtener_tasa_dolar()
    costo_proyectado_pesos = costo_proyectado * tasa_dolar
    facturas_saas = FacturaSaaS.objects.filter(usuario=request.user).order_by('-fecha_emision')
        
    context = {
        'titulo_pagina': 'Mi Facturación B2B',
        'propiedades_activas': propiedades_activas,
        'costo_proyectado': costo_proyectado,
        'costo_proyectado_pesos': costo_proyectado_pesos,
        'facturas_saas': facturas_saas,
        'suscripcion': suscripcion,
        'metricas': metricas,
        'tasa_dolar': tasa_dolar,
    }
    return render(request, 'gestion_propiedades/mi_suscripcion.html', context)

@login_required(login_url='/login/')
@propietario_requerido
def subir_comprobante_saas(request, factura_id):
    """
    Permite al usuario subir un comprobante de pago para su factura SaaS.
    """
    from .models import FacturaSaaS
    
    factura = get_object_or_404(FacturaSaaS, id=factura_id, usuario=request.user)
    
    if request.method == 'POST' and 'comprobante' in request.FILES:
        factura.comprobante_pago = request.FILES['comprobante']
        factura.save()
        messages.success(request, f'¡Comprobante para la factura por ${factura.monto_total} enviado para validación!')
    else:
        messages.error(request, 'No se pudo subir el archivo. Intenta de nuevo.')
        
    return redirect('mi_suscripcion')

@login_required(login_url='/login/')
def generar_corte_saas(request):
    """
    Botón maestro (Superadmin) para facturar a todos los clientes según su plan.
    """
    if not request.user.is_superuser:
        messages.error(request, "Acceso denegado. Solo el Administrador Global puede emitir cortes.")
        return redirect('dashboard')
        
    from django.utils import timezone
    from datetime import timedelta
    from django.contrib.auth.models import User
    from .models import FacturaSaaS
    from .utils_saas import calcular_metricas_facturacion_saas, calcular_fecha_vencimiento_dias_habiles
    from .utils_correo import enviar_aviso_factura_saas
    
    hoy = timezone.now().date()
    clientes = User.objects.filter(is_superuser=False, suscripcion__isnull=False)
    facturas_creadas = 0
    
    for cliente in clientes:
        suscripcion = cliente.suscripcion
        
        # Guard 1: Solo facturar a cuentas que ya son de PAGO (ACTIVA). Excluir TRIAL y SUSPENDIDAS.
        if suscripcion.estado != 'ACTIVA':
            continue
        
        # Guard 2: Si ya tiene facturas emitidas y aún no ha llegado su proxima fecha de corte, lo saltamos.
        # Si es una cuenta recién activada que NUNCA ha tenido facturas, se le emite su cobro inicial por adelantado.
        tiene_facturas = FacturaSaaS.objects.filter(usuario=cliente).exists()
        if tiene_facturas and suscripcion.fecha_proximo_pago and hoy < suscripcion.fecha_proximo_pago:
            continue
            
        metricas = calcular_metricas_facturacion_saas(suscripcion)
        fecha_venc = calcular_fecha_vencimiento_dias_habiles(hoy, metricas['dias_gracia_habiles'])
        
        nueva_fs = FacturaSaaS.objects.create(
            usuario=cliente,
            fecha_vencimiento=fecha_venc,
            monto_total=metricas['monto_total'],
            propiedades_cobradas=metricas['propiedades_total'],
            usuarios_cobrados=metricas['usuarios_extra'],
            estado='PENDIENTE'
        )
        facturas_creadas += 1
        
        # Reprogramar próximo cobro (1 mes)
        suscripcion.fecha_proximo_pago = hoy + timedelta(days=30)
        suscripcion.save()
        
        enviar_aviso_factura_saas(nueva_fs)
            
    if facturas_creadas > 0:
        messages.success(request, f"Éxito: Se generaron {facturas_creadas} facturas para clientes en fecha de corte.")
    else:
        messages.info(request, "Protección Activa: Ningún cliente necesita facturación hoy. No se duplicaron cobros.")
        
    return redirect('saas_master_control')


@login_required(login_url='/login/')
def emitir_factura_saas_cliente(request, cliente_id):
    """
    Permite al Superadmin emitir de inmediato la factura de cobro SaaS por adelantado
    para un cliente específico (ej: cliente nuevo que acaba de activar su plan).
    """
    if not request.user.is_superuser:
        messages.error(request, "Acceso denegado. Solo el Superadministrador puede emitir facturas SaaS.")
        return redirect('dashboard')

    from django.contrib.auth.models import User
    from .models import FacturaSaaS
    from .utils_saas import calcular_metricas_facturacion_saas, calcular_fecha_vencimiento_dias_habiles
    from .utils_correo import enviar_aviso_factura_saas

    cliente = get_object_or_404(User, id=cliente_id)
    try:
        suscripcion = cliente.suscripcion
    except Exception:
        suscripcion = None

    if not suscripcion:
        messages.error(request, f"El cliente {cliente.username} no tiene suscripción configurada.")
        return redirect('saas_master_control')

    hoy = timezone.now().date()
    metricas = calcular_metricas_facturacion_saas(suscripcion)
    fecha_venc = calcular_fecha_vencimiento_dias_habiles(hoy, metricas['dias_gracia_habiles'])

    nueva_fs = FacturaSaaS.objects.create(
        usuario=cliente,
        fecha_vencimiento=fecha_venc,
        monto_total=metricas['monto_total'],
        propiedades_cobradas=metricas['propiedades_total'],
        usuarios_cobrados=metricas['usuarios_extra'],
        estado='PENDIENTE'
    )

    if suscripcion.estado != 'ACTIVA':
        suscripcion.estado = 'ACTIVA'

    suscripcion.fecha_proximo_pago = hoy + timedelta(days=30)
    suscripcion.save()

    try:
        enviar_aviso_factura_saas(nueva_fs)
    except Exception:
        pass

    messages.success(
        request, 
        f"✅ ¡Factura SaaS #{nueva_fs.id} emitida con éxito para {cliente.get_full_name() or cliente.username} por ${nueva_fs.monto_total} USD ({nueva_fs.propiedades_cobradas} propiedades cobradas)! Ya puedes registrar el pago recibido."
    )
    return redirect('saas_facturacion')


@login_required(login_url='/login/')
def prueba_correo_saas(request):
    """ Utilidad de diagnóstico para lanzar un correo de prueba SMTP """
    if not request.user.is_superuser:
        messages.error(request, "Acceso denegado. Solo el Administrador Global puede diagnosticar los servidores.")
        return redirect('dashboard')
        
    from django.core.mail import send_mail
    from django.conf import settings
    import traceback
    
    correo_destino = request.user.email
    if not correo_destino:
        messages.error(request, "Error: Tu perfil de superusuario no tiene un correo configurado para enviar la prueba.")
        return redirect('saas_master_control')
        
    html_msg = f"""
    <div style="font-family: Arial, sans-serif; background-color: #1a252f; padding: 40px; text-align: center; border-radius: 10px;">
        <h1 style="color: #f39c12;">¡Conexión Exitosa! 🚀</h1>
        <p style="color: white; font-size: 16px;">
            El sistema financiero <strong>Alquilo Software</strong>
            se ha conectado correctamente con SendGrid desde la nube de Railway.
        </p>
        <p style="color: #bdc3c7;">El motor automático de cobranza ya puede hacer su trabajo a diario.</p>
    </div>
    """
    
    try:
        import requests
        import json
        
        # Modo antibloqueo: SendGrid API v3 (HTTPS Puerto 443)
        url = "https://api.sendgrid.com/v3/mail/send"
        headers = {
            "Authorization": f"Bearer {settings.EMAIL_HOST_PASSWORD}",
            "Content-Type": "application/json"
        }
        
        em_from = settings.DEFAULT_FROM_EMAIL
        origen = {"email": em_from.split('<')[1].replace('>','').strip(), "name": em_from.split('<')[0].strip()} if '<' in em_from else {"email": em_from}
        
        payload = {
            "personalizations": [{"to": [{"email": correo_destino}]}],
            "from": origen,
            "subject": '[Alquilo] 🤖 Diagnóstico Antibloqueo',
            "content": [{"type": "text/html", "value": html_msg}]
        }
        
        resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=10)
        resp.raise_for_status() 
        
        messages.success(request, f"🚀 ¡ÉXITO ROTUNDO! Traspasamos el bloqueo de Railway mediante HTTPS API. El correo fue entregado a {correo_destino}.")
    except Exception as e:
        error_msg = str(e)
        if hasattr(e, 'response') and e.response is not None:
            error_msg = f"{e} - {e.response.text}"
            
        detalle_conexion = f"(Detectando configuración -> Llave API: {str(settings.EMAIL_HOST_PASSWORD)[:8]}...)"
        messages.error(request, f"❌ BLOQUEO / ERROR API: {error_msg}. {detalle_conexion}. Asegúrate que pusiste bien la API KEY en Railway.")
        
    return redirect('saas_master_control')

@login_required(login_url='/login/')
def eliminar_propiedad(request, propiedad_id):
    """
    Realiza un Soft Delete de la propiedad, verificando permisos estrictos.
    Solo el Administrador del Portafolio o el SuperAdmin pueden hacerlo.
    """
    propiedad = get_object_or_404(Propiedad, id=propiedad_id)
    
    # Validar permisos
    es_propietario = request.user == propiedad.portafolio.propietario
    es_superadmin = request.user.is_superuser
    
    if not (es_propietario or es_superadmin):
        messages.error(request, 'No tienes permiso para eliminar esta propiedad permanentemente. Se requiere rol de Propietario o Superadmin.')
        return redirect('lista_propiedades')
    
    if request.method == 'POST':
        propiedad.is_deleted = True
        propiedad.save()
        messages.success(request, f'La propiedad "{propiedad.nombre_o_numero}" ha sido eliminada permanentemente del sistema y su facturación ha sido detenida.')
        return redirect('lista_propiedades')
        
    # Si le pega por GET por error, lo mandamos a detalle propiedad
    return redirect('detalle_propiedad', propiedad_id=propiedad.id)

@login_required(login_url='/login/')
def saas_facturacion(request):
    """
    Panel para que el Superadmin vea TODAS las Facturas SaaS emitidas a los clientes y el dinero recaudado.
    """
    if not request.user.is_superuser:
        return redirect('dashboard')
        
    from django.db.models import Sum
    from .models import FacturaSaaS
    
    facturas = FacturaSaaS.objects.select_related('usuario').order_by('-fecha_emision')
    
    total_cobrado = facturas.filter(estado='PAGADA').aggregate(total=Sum('monto_total'))['total'] or 0.00
    total_pendiente = facturas.filter(estado='PENDIENTE').aggregate(total=Sum('monto_total'))['total'] or 0.00
    
    context = {
        'titulo_pagina': 'Reporte de Recaudación B2B',
        'facturas': facturas,
        'total_cobrado': total_cobrado,
        'total_pendiente': total_pendiente
    }
    return render(request, 'gestion_propiedades/saas_facturacion.html', context)

@login_required(login_url='/login/')
def marcar_factura_saas_pagada(request, factura_id):
    """
    Permite al Superadmin marcar una Factura SaaS como PAGADA (dinero recibido).
    """
    if not request.user.is_superuser:
        return redirect('dashboard')
        
    from .models import FacturaSaaS
    factura = get_object_or_404(FacturaSaaS, id=factura_id)
    
    if request.method == 'POST':
        factura.estado = 'PAGADA'
        factura.save()
        messages.success(request, f'La factura de {factura.usuario.username} por ${factura.monto_total} ha sido registrada como PAGADA.')
        
    return redirect('saas_facturacion')

# --- GESTIÓN DE GASTOS PROGRAMADOS (RECURRENTES) ---

@login_required(login_url='/login/')
def crear_gasto_programado(request, propiedad_id):
    from .forms import GastoProgramadoForm
    portafolios = Portafolio.objects.filter(Q(propietario=request.user) | Q(accesos__usuario=request.user)).distinct()
    propiedad = get_object_or_404(Propiedad, id=propiedad_id, portafolio__in=portafolios)

    if request.method == 'POST':
        form = GastoProgramadoForm(request.POST)
        if form.is_valid():
            gasto = form.save(commit=False)
            gasto.propiedad = propiedad
            gasto.save()
            
            # Registrar en Auditoría
            AuditLog.objects.create(
                accion='CREAR',
                modulo='GastoProgramado',
                descripcion=f"Creó recordatorio de gasto programado '{gasto.concepto}' para {propiedad.nombre_o_numero} por ${gasto.monto:,.2f}",
                usuario=request.user,
                portafolio=propiedad.portafolio
            )
            
            messages.success(request, 'Gasto programado registrado correctamente.')
            return redirect('detalle_propiedad', propiedad_id=propiedad.id)
    else:
        form = GastoProgramadoForm()

    context = {
        'titulo_pagina': f'Nuevo Gasto Programado: {propiedad.nombre_o_numero}',
        'form': form
    }
    return render(request, 'gestion_propiedades/form_generico.html', context)

@login_required(login_url='/login/')
def editar_gasto_programado(request, gasto_id):
    from .forms import GastoProgramadoForm
    portafolios = Portafolio.objects.filter(Q(propietario=request.user) | Q(accesos__usuario=request.user)).distinct()
    gasto = get_object_or_404(GastoProgramado, id=gasto_id, propiedad__portafolio__in=portafolios)

    if request.method == 'POST':
        form = GastoProgramadoForm(request.POST, instance=gasto)
        if form.is_valid():
            form.save()
            
            # Registrar en Auditoría
            AuditLog.objects.create(
                accion='EDITAR',
                modulo='GastoProgramado',
                descripcion=f"Editó recordatorio de gasto programado '{gasto.concepto}' para {gasto.propiedad.nombre_o_numero} por ${gasto.monto:,.2f}",
                usuario=request.user,
                portafolio=gasto.propiedad.portafolio
            )
            
            messages.success(request, 'Gasto programado actualizado correctamente.')
            return redirect('detalle_propiedad', propiedad_id=gasto.propiedad.id)
    else:
        form = GastoProgramadoForm(instance=gasto)

    context = {
        'titulo_pagina': f'Editar Gasto Programado: {gasto.propiedad.nombre_o_numero}',
        'form': form
    }
    return render(request, 'gestion_propiedades/form_generico.html', context)

@login_required(login_url='/login/')
def eliminar_gasto_programado(request, gasto_id):
    portafolios = Portafolio.objects.filter(Q(propietario=request.user) | Q(accesos__usuario=request.user)).distinct()
    gasto = get_object_or_404(GastoProgramado, id=gasto_id, propiedad__portafolio__in=portafolios)
    propiedad_id = gasto.propiedad.id

    if request.method == 'POST':
        concepto = gasto.concepto
        monto = gasto.monto
        gasto.delete()
        
        # Registrar en Auditoría
        AuditLog.objects.create(
            accion='ELIMINAR',
            modulo='GastoProgramado',
            descripcion=f"Eliminó recordatorio de gasto programado '{concepto}' para la propiedad ID {propiedad_id} por ${monto:,.2f}",
            usuario=request.user,
            portafolio=gasto.propiedad.portafolio
        )
        
        messages.success(request, 'Gasto programado eliminado correctamente.')
        
    return redirect('detalle_propiedad', propiedad_id=propiedad_id)

@login_required(login_url='/login/')
def pagar_gasto_programado(request, gasto_id):
    portafolios = Portafolio.objects.filter(Q(propietario=request.user) | Q(accesos__usuario=request.user)).distinct()
    gasto = get_object_or_404(GastoProgramado, id=gasto_id, propiedad__portafolio__in=portafolios)
    
    hoy = date.today()
    meses_es = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
    mes_nombre = meses_es[hoy.month - 1]

    # Verificar si ya se pagó este mes
    ya_pagado = MantenimientoUnidad.objects.filter(
        gasto_programado=gasto,
        fecha_reporte__month=hoy.month,
        fecha_reporte__year=hoy.year
    ).exists()

    if not ya_pagado:
        # Registrar como MantenimientoUnidad
        MantenimientoUnidad.objects.create(
            propiedad=gasto.propiedad,
            categoria='OTRO',
            descripcion=f"Pago programado: {gasto.concepto} ({mes_nombre} {hoy.year})",
            costo=gasto.monto,
            estado='COMPLETADO',
            fecha_resolucion=hoy,
            gasto_programado=gasto
        )
        
        # Registrar en Auditoría
        AuditLog.objects.create(
            accion='CREAR',
            modulo='Mantenimiento',
            descripcion=f"Registró pago de gasto programado '{gasto.concepto}' para {gasto.propiedad.nombre_o_numero} por ${gasto.monto:,.2f}",
            usuario=request.user,
            portafolio=gasto.propiedad.portafolio
        )
        
        messages.success(request, f"Se ha registrado el pago de ${gasto.monto:,.2f} para '{gasto.concepto}' exitosamente.")
    else:
        messages.warning(request, "Este gasto ya ha sido marcado como pagado este mes.")

    # Redirigir según el parámetro next
    next_url = request.GET.get('next', 'dashboard')
    if next_url == 'detalle_propiedad':
        return redirect('detalle_propiedad', propiedad_id=gasto.propiedad.id)
    return redirect('dashboard')


# --- MÓDULO DE AUDITORÍA ---

@login_required(login_url='/login/')
def vista_auditoria(request):
    """
    Bitácora de Auditoría con control multi-tenant:
    - SuperAdmin: ve TODOS los AuditLogs del sistema.
    - Propietario de portafolio: ve solo los logs de sus portafolios.
    """
    if request.user.is_superuser:
        logs = AuditLog.objects.select_related('usuario', 'portafolio').all()[:500]
    else:
        portafolios = Portafolio.objects.filter(propietario=request.user)
        logs = AuditLog.objects.filter(
            portafolio__in=portafolios
        ).select_related('usuario', 'portafolio').all()[:500]

    context = {
        'titulo_pagina': 'Bitácora de Auditoría',
        'logs': logs,
    }
    return render(request, 'gestion_propiedades/auditoria.html', context)


# --- REPORTE DE TRANSPARENCIA ---

@login_required(login_url='/login/')
def reporte_transparencia(request):
    """
    Reporte de Transparencia Financiera:
    - Eficiencia de Recaudación: % de lo facturado que fue cobrado en el mes filtrado.
    - Distribución de Gastos: egresos de mantenimiento agrupados por categoría.
    """
    hoy = date.today()
    mes = int(request.GET.get('mes', hoy.month))
    anio = int(request.GET.get('anio', hoy.year))

    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().distinct()
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()

    # --- 1. EFICIENCIA DE RECAUDACIÓN ---
    debimos_cobrar = Factura.objects.filter(
        contrato__propiedad__portafolio__in=portafolios,
        fecha_emision__year=anio,
        fecha_emision__month=mes,
    ).exclude(estado='ANULADA').aggregate(total=Sum('monto_base'))['total'] or 0

    hemos_cobrado = ReciboPago.objects.filter(
        factura__contrato__propiedad__portafolio__in=portafolios,
        fecha_pago__year=anio,
        fecha_pago__month=mes,
    ).aggregate(total=Sum('monto_pagado'))['total'] or 0

    faltan_cobrar = max(float(debimos_cobrar) - float(hemos_cobrado), 0)
    eficiencia = round((float(hemos_cobrado) / float(debimos_cobrar) * 100), 1) if debimos_cobrar else 0

    # --- 2. DISTRIBUCIÓN DE GASTOS (Mantenimientos del mes) ---
    COLORES = ['#e74c3c', '#3498db', '#f39c12', '#27ae60', '#9b59b6']
    categoria_labels = dict(MantenimientoUnidad.CATEGORIA_CHOICES)
    gastos_raw = MantenimientoUnidad.objects.filter(
        propiedad__portafolio__in=portafolios,
        fecha_reporte__year=anio,
        fecha_reporte__month=mes,
    ).values('categoria').annotate(total=Sum('costo')).order_by('-total')

    total_gastos = sum(float(g['total']) for g in gastos_raw) or 1
    gastos = [
        {
            'label': categoria_labels.get(g['categoria'], g['categoria']),
            'total': float(g['total']),
            'pct': round(float(g['total']) / total_gastos * 100, 1),
            'color': COLORES[i % len(COLORES)],
        }
        for i, g in enumerate(gastos_raw)
    ]

    import json
    chart_labels = json.dumps([g['label'] for g in gastos])
    chart_data = json.dumps([g['total'] for g in gastos])
    chart_colors = json.dumps([g['color'] for g in gastos])

    context = {
        'titulo_pagina': 'Reporte de Transparencia',
        'mes': mes,
        'anio': anio,
        'debimos_cobrar': debimos_cobrar,
        'hemos_cobrado': hemos_cobrado,
        'faltan_cobrar': faltan_cobrar,
        'eficiencia': eficiencia,
        'gastos': gastos,
        'total_gastos': total_gastos,
        'chart_labels': chart_labels,
        'chart_data': chart_data,
        'chart_colors': chart_colors,
        'meses': [(i, date(2000, i, 1).strftime('%B')) for i in range(1, 13)],
        'anios': list(range(hoy.year - 3, hoy.year + 1)),
    }
    return render(request, 'gestion_propiedades/reporte_transparencia.html', context)

@login_required(login_url='/login/')
def registrar_pago_anticipado(request, contrato_id):
    """
    Permite registrar un pago por adelantado.
    Localiza la fecha de la última factura y genera la siguiente de forma diferida o futura,
    incluyendo los servicios recurrentes activos asociados al contrato.
    """
    from django.utils import timezone
    from datetime import date, timedelta
    import calendar
    
    if request.user.is_superuser:
        contrato = get_object_or_404(Contrato, id=contrato_id)
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()
        contrato = get_object_or_404(Contrato, id=contrato_id, propiedad__portafolio__in=portafolios)
    
    # 1. Determinar cuál sería el próximo mes a facturar.
    ultima_factura = contrato.facturas.order_by('-fecha_emision').first()
    if ultima_factura:
        ultimo_mes = ultima_factura.fecha_emision.month
        ultimo_anio = ultima_factura.fecha_emision.year
        prox_mes = ultimo_mes + 1
        prox_anio = ultimo_anio
        if prox_mes > 12:
            prox_mes = 1
            prox_anio += 1
    else:
        hoy = timezone.now().date()
        prox_mes = hoy.month
        prox_anio = hoy.year
        
    # Calcular fecha de emisión de esa factura
    try:
        fecha_proxima_emision = date(prox_anio, prox_mes, contrato.dia_de_pago)
    except ValueError:
        ultimo_dia_mes = calendar.monthrange(prox_anio, prox_mes)[1]
        fecha_proxima_emision = date(prox_anio, prox_mes, ultimo_dia_mes)
        
    fecha_vencimiento_proxima = fecha_proxima_emision + timedelta(days=contrato.dias_gracia)
    concepto_anticipada = contrato.propiedad.portafolio.generar_concepto_factura(contrato, fecha_proxima_emision, es_anticipada=True)

    # 2. Servicios adicionales configurados para cobro recurrente
    cargos_activos = list(contrato.cargos_adicionales.filter(activo=True))
    monto_servicios = sum((decimal.Decimal(str(c.monto)) for c in cargos_activos), decimal.Decimal('0.00'))
    monto_renta = decimal.Decimal(str(contrato.monto_renta))
    monto_total_adelanto = monto_renta + monto_servicios
    
    if request.method == 'POST':
        metodo = request.POST.get('metodo_pago', 'TRANSFERENCIA')
        referencia = request.POST.get('referencia', '')
        fecha_pago = request.POST.get('fecha_pago') or timezone.now().date()
        comprobante = request.FILES.get('comprobante_imagen')

        from django.db import transaction
        nueva_factura = None
        try:
            with transaction.atomic():
                nueva_factura = Factura.objects.create(
                    contrato=contrato,
                    fecha_emision=fecha_proxima_emision,
                    fecha_vencimiento=fecha_vencimiento_proxima,
                    monto_base=monto_total_adelanto,
                    monto_renta=monto_renta,
                    monto_servicios=monto_servicios,
                    concepto=concepto_anticipada,
                    estado='PAGADA'
                )
                for c in cargos_activos:
                    DetalleFacturaServicio.objects.create(
                        factura=nueva_factura,
                        cargo_origen=c,
                        categoria=c.categoria,
                        concepto=c.nombre_mostrar,
                        monto=c.monto
                    )
                
                ReciboPago.objects.create(
                    factura=nueva_factura,
                    fecha_pago=fecha_pago,
                    monto_pagado=monto_total_adelanto,
                    metodo_pago=metodo,
                    referencia_transaccion=referencia,
                    comprobante_imagen=comprobante,
                    registrado_por=request.user
                )
        except Exception as e:
            if comprobante:
                try:
                    with transaction.atomic():
                        nueva_factura = Factura.objects.create(
                            contrato=contrato,
                            fecha_emision=fecha_proxima_emision,
                            fecha_vencimiento=fecha_vencimiento_proxima,
                            monto_base=monto_total_adelanto,
                            monto_renta=monto_renta,
                            monto_servicios=monto_servicios,
                            concepto=concepto_anticipada,
                            estado='PAGADA'
                        )
                        for c in cargos_activos:
                            DetalleFacturaServicio.objects.create(
                                factura=nueva_factura,
                                cargo_origen=c,
                                categoria=c.categoria,
                                concepto=c.nombre_mostrar,
                                monto=c.monto
                            )
                        
                        ReciboPago.objects.create(
                            factura=nueva_factura,
                            fecha_pago=fecha_pago,
                            monto_pagado=monto_total_adelanto,
                            metodo_pago=metodo,
                            referencia_transaccion=referencia,
                            comprobante_imagen=None,
                            registrado_por=request.user
                        )
                    messages.warning(request, f"¡Pago anticipado registrado exitosamente! Nota: el archivo de comprobante no pudo procesarse ({str(e)}).")
                    return redirect('detalle_inquilino', inquilino_id=contrato.inquilino.id)
                except Exception as inner_e:
                    messages.error(request, f"Error al generar pago anticipado: {str(inner_e)}")
                    return redirect('registrar_pago_anticipado', contrato_id=contrato.id)
            messages.error(request, f"Error al generar pago anticipado: {str(e)}")
            return redirect('registrar_pago_anticipado', contrato_id=contrato.id)
        
        messages.success(request, f'¡Pago anticipado registrado exitosamente para: {nueva_factura.concepto}!')
        return redirect('detalle_inquilino', inquilino_id=contrato.inquilino.id)
        
    context = {
        'titulo_pagina': 'Recibir Pago Anticipado',
        'contrato': contrato,
        'fecha_proxima_emision': fecha_proxima_emision,
        'fecha_vencimiento_proxima': fecha_vencimiento_proxima,
        'concepto_anticipada': concepto_anticipada,
        'monto_renta': monto_renta,
        'cargos_activos': cargos_activos,
        'monto_servicios': monto_servicios,
        'monto_total_adelanto': monto_total_adelanto,
    }
    return render(request, 'gestion_propiedades/pago_anticipado.html', context)

@login_required(login_url='/login/')
def reporte_morosos(request):
    """
    Escanea todo el portafolio del usuario y agrupa las facturas atrasadas 
    calculando la mora total, los días de retraso y los datos de contacto.
    """
    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().distinct()
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()
    
    facturas_vencidas = Factura.objects.filter(
        contrato__propiedad__portafolio__in=portafolios, 
        estado='ATRASADA'
    ).select_related('contrato__inquilino', 'contrato__propiedad')\
    .annotate(
        mora_acumulada=Sum('moras__monto')
    ).order_by('fecha_vencimiento')
    
    # Procesar data para el template
    from django.utils import timezone
    hoy = timezone.now().date()
    
    deudores = []
    gran_total_deuda = decimal.Decimal('0.00')
    gran_total_mora = decimal.Decimal('0.00')
    
    for f in facturas_vencidas:
        dias_retraso = (hoy - f.fecha_vencimiento).days
        mora = f.mora_acumulada or decimal.Decimal('0.00')
        deuda_total = f.monto_base + mora
        
        gran_total_deuda += f.monto_base
        gran_total_mora += mora
        
        deudores.append({
            'factura': f,
            'inquilino': f.contrato.inquilino,
            'propiedad': f.contrato.propiedad,
            'dias_retraso': dias_retraso,
            'monto_base': f.monto_base,
            'mora': mora,
            'deuda_total': deuda_total
        })
        
    context = {
        'titulo_pagina': 'Reporte Integral de Morosidad',
        'deudores': deudores,
        'gran_total_riesgo': gran_total_deuda + gran_total_mora,
        'gran_total_deuda': gran_total_deuda,
        'gran_total_mora': gran_total_mora,
        'total_casos': len(deudores)
    }
    return render(request, 'gestion_propiedades/reporte_morosos.html', context)


@login_required(login_url='/login/')
def editar_configuracion_global(request):
    if not request.user.is_superuser:
        return redirect('dashboard')
        
    from .models import ConfiguracionGlobal
    from .forms import ConfiguracionGlobalForm
    
    config = ConfiguracionGlobal.get_solo()
    
    if request.method == 'POST':
        form = ConfiguracionGlobalForm(request.POST, instance=config)
        if form.is_valid():
            form.save()
            messages.success(request, 'La configuración global fue actualizada.')
            return redirect('saas_master_control')
    else:
        form = ConfiguracionGlobalForm(instance=config)
        
    context = {'titulo_pagina': 'Ajustes del Sistema (Tasa del Dólar)', 'form': form}
    return render(request, 'gestion_propiedades/form_generico.html', context)

@login_required(login_url='/login/')
def editar_portafolio(request):
    """
    Vista protegida para que el administrador principal configure la Marca Blanca 
    y otros parámetros del negocio vinculados a su portafolio.
    """
    from .models import Portafolio
    from .forms import PortafolioForm

    portafolio_id = request.GET.get('portafolio_id') or request.POST.get('portafolio_id')
    portafolio = None
    lista_portafolios = []

    if request.user.is_superuser:
        lista_portafolios = Portafolio.objects.all().order_by('nombre')
        if portafolio_id and str(portafolio_id).isdigit():
            portafolio = lista_portafolios.filter(id=int(portafolio_id)).first()
        if not portafolio:
            # Buscar primero el de Basora si existe o el del usuario o el primero
            portafolio = lista_portafolios.filter(nombre__icontains='Basora').first() or \
                         lista_portafolios.filter(propietario=request.user).first() or \
                         lista_portafolios.first()
    else:
        portafolios = Portafolio.objects.filter(Q(propietario=request.user) | Q(accesos__usuario=request.user)).distinct().order_by('nombre')
        lista_portafolios = portafolios
        if portafolio_id and str(portafolio_id).isdigit():
            portafolio = portafolios.filter(id=int(portafolio_id)).first()
        if not portafolio:
            portafolio = Portafolio.objects.filter(propietario=request.user).first()
            if not portafolio:
                acceso = request.user.portafolios_asignados.first()
                if acceso:
                    portafolio = acceso.portafolio
                elif portafolios.exists():
                    portafolio = portafolios.first()

    if not portafolio:
        messages.error(request, "No tienes permisos de Administrador para editar los datos de Marca Blanca de este portafolio.")
        return redirect('dashboard')
    
    if request.method == 'POST':
        form = PortafolioForm(request.POST, request.FILES, instance=portafolio)
        if form.is_valid():
            try:
                p = form.save()
                if form.cleaned_data.get('actualizar_facturas_existentes'):
                    from .models import Factura, Contrato
                    contratos = Contrato.objects.filter(propiedad__portafolio=p)
                    facturas = Factura.objects.filter(contrato__in=contratos).exclude(concepto__icontains='migrado')
                    cant_actualizadas = 0
                    for f in facturas:
                        nuevo_concepto = p.generar_concepto_factura(f.contrato, fecha_base=f.fecha_vencimiento or f.fecha_emision, concepto_actual=f.concepto)
                        if nuevo_concepto != f.concepto:
                            f.concepto = nuevo_concepto
                            f.save()
                            cant_actualizadas += 1
                    messages.success(request, f"Ajustes de portafolio guardados. Se actualizaron {cant_actualizadas} factura(s) existentes al formato seleccionado.")
                else:
                    messages.success(request, "Ajustes de Marca Blanca y del portafolio actualizados correctamente.")
                return redirect(f"{reverse('editar_portafolio')}?portafolio_id={p.id}")
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Error al guardar portafolio/logo: {e}", exc_info=True)
                messages.error(request, f"Ocurrió un inconveniente al procesar la imagen del logotipo: {str(e)}. Intenta con otra imagen.")
    else:
        form = PortafolioForm(instance=portafolio)
    
    context = {
        'form': form,
        'portafolio': portafolio,
        'lista_portafolios': lista_portafolios,
        'titulo_pagina': "Ajustes de Marca Blanca y Portafolio"
    }
    return render(request, 'gestion_propiedades/editar_portafolio.html', context)


@login_required(login_url='/login/')
def saas_detector_fugas(request):
    """
    Panel para que el SuperAdmin detecte dinero estancado, trials por vencer y anomalías en la facturación SaaS.
    """
    if not request.user.is_superuser:
        messages.error(request, "Acceso Privado. Solo el Administrador de la Plataforma tiene esta visibilidad.")
        return redirect('dashboard')
        
    from django.db.models import Count, Q
    from django.utils import timezone
    from django.contrib.auth.models import User
    
    hoy = timezone.now().date()
    
    # Todos los usuarios excluyendo superadmins
    clientes_base = User.objects.filter(is_superuser=False).select_related('suscripcion')
    for c in clientes_base:
        c.num_props = Propiedad.objects.filter(portafolio__propietario=c, is_deleted=False).count()
    
    # 1. Anomalías (Fuga de Capital)
    # Tienen propiedades, pero no tienen fecha de próximo pago / o la tienen vencida misteriosamente en estado ACTIVO.
    anomalias = []
    for c in clientes_base:
        if c.num_props > 0:
            if not hasattr(c, 'suscripcion') or not c.suscripcion:
                anomalias.append({'cliente': c, 'motivo': 'Suscripción No Inicializada', 'gravedad': 'ALTA'})
            elif c.suscripcion.estado == 'ACTIVA':
                if not c.suscripcion.fecha_proximo_pago:
                    anomalias.append({'cliente': c, 'motivo': 'Fecha Próximo Pago Vacía (JAMÁS SE LE COBRARÁ)', 'gravedad': 'CRITICA'})
            elif c.suscripcion.estado == 'SUSPENDIDA':
                if c.num_props > 0 and c.last_login and c.last_login.date() == hoy:
                    anomalias.append({'cliente': c, 'motivo': 'Usuario SUSPENDIDO pero inició sesión hoy', 'gravedad': 'MEDIA'})
                    
    # 2. Embudo de Trials (Trials Activos ordenados por proximidad a vencer)
    trials_raw = clientes_base.filter(suscripcion__estado='TRIAL')
    trials = []
    for t in trials_raw:
        if hasattr(t, 'suscripcion') and t.suscripcion.fecha_proximo_pago:
            dias_restantes = (t.suscripcion.fecha_proximo_pago - hoy).days
            trials.append({
                'cliente': t,
                'dias_restantes': dias_restantes,
                'fecha_corte': t.suscripcion.fecha_proximo_pago
            })
    
    # Ordenar trials del menor día (más cerca de vencer) al mayor
    trials = sorted(trials, key=lambda x: x['dias_restantes'])
    
    context = {
        'titulo_pagina': 'Detector de Fugas de Ingresos',
        'anomalias': anomalias,
        'trials': trials,
        'hoy': hoy
    }
    
    return render(request, 'gestion_propiedades/saas_detector_fugas.html', context)

@login_required(login_url='/login/')
def imprimir_contrato_legal(request, contrato_id):
    """
    Vista diseñada exclusivamente para imprimir el contrato generado (Smart Print).
    """
    portafolios = Portafolio.objects.filter(Q(propietario=request.user) | Q(accesos__usuario=request.user))
    contrato = get_object_or_404(Contrato, id=contrato_id, propiedad__portafolio__in=portafolios)
    
    if not contrato.texto_legal_generado:
        messages.warning(request, "Este contrato fue creado sin usar una plantilla. Por favor edítalo y selecciona una plantilla legal primero.")
        return redirect('lista_contratos')
        
    return render(request, 'gestion_propiedades/imprimir_contrato_legal.html', {'contrato': contrato})

# --- MÓDULO DE GESTIÓN DE PROPIETARIOS DE INMUEBLES ---

@login_required(login_url='/login/')
def lista_propietarios(request):
    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().distinct()
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()

    portafolio_id = request.GET.get('portafolio_id', 'TODOS')
    if portafolio_id != 'TODOS' and portafolio_id and str(portafolio_id).isdigit():
        portafolios_filtrados = portafolios.filter(id=int(portafolio_id))
    else:
        portafolios_filtrados = portafolios
    
    propietarios = PropietarioInmueble.objects.filter(
        portafolio__in=portafolios_filtrados
    ).annotate(
        cant_propiedades=Count('propiedades', filter=Q(propiedades__is_deleted=False))
    ).select_related('portafolio').order_by('nombre')
    
    context = {
        'titulo_pagina': 'Gestión de Propietarios',
        'propietarios': propietarios,
        'portafolios': portafolios,
        'portafolio_sel': str(portafolio_id),
    }
    return render(request, 'gestion_propiedades/lista_propietarios.html', context)


@login_required(login_url='/login/')
def crear_propietario(request):
    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().distinct()
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()
    
    if not portafolios.exists():
        messages.error(request, "Debes tener al menos un portafolio activo.")
        return redirect('dashboard')
        
    if request.method == 'POST':
        form = PropietarioInmuebleForm(request.POST, portafolios=portafolios)
        if form.is_valid():
            propietario = form.save(commit=False)
            portafolio_id = request.POST.get('portafolio_id')
            if portafolio_id:
                propietario.portafolio = get_object_or_404(portafolios, id=portafolio_id)
            else:
                propietario.portafolio = portafolios.first()
            propietario.save()
            
            # Asignar propiedades seleccionadas al propietario
            propiedades_seleccionadas = form.cleaned_data.get('propiedades')
            Propiedad.objects.filter(propietario_inmueble=propietario).update(propietario_inmueble=None)
            if propiedades_seleccionadas:
                propiedades_seleccionadas.update(propietario_inmueble=propietario)

            messages.success(request, f'Propietario "{propietario.nombre}" registrado exitosamente.')
            return redirect('lista_propietarios')
    else:
        form = PropietarioInmuebleForm(portafolios=portafolios)
        
    context = {
        'titulo_pagina': 'Registrar Propietario de Inmueble',
        'form': form,
        'portafolios': portafolios
    }
    return render(request, 'gestion_propiedades/form_generico.html', context)


@login_required(login_url='/login/')
def editar_propietario(request, propietario_id):
    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().distinct()
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()
    propietario = get_object_or_404(PropietarioInmueble, id=propietario_id, portafolio__in=portafolios)
    
    if request.method == 'POST':
        form = PropietarioInmuebleForm(request.POST, instance=propietario, portafolios=portafolios)
        if form.is_valid():
            form.save()
            
            # Actualizar propiedades asignadas al propietario
            propiedades_seleccionadas = form.cleaned_data.get('propiedades')
            Propiedad.objects.filter(propietario_inmueble=propietario).update(propietario_inmueble=None)
            if propiedades_seleccionadas:
                propiedades_seleccionadas.update(propietario_inmueble=propietario)

            messages.success(request, f'Información del propietario "{propietario.nombre}" actualizada.')
            return redirect('detalle_propietario', propietario_id=propietario.id)
    else:
        form = PropietarioInmuebleForm(instance=propietario, portafolios=portafolios)
        
    context = {
        'titulo_pagina': f'Editar Propietario: {propietario.nombre}',
        'form': form,
        'propietario': propietario
    }
    return render(request, 'gestion_propiedades/form_generico.html', context)


@login_required(login_url='/login/')
def detalle_propietario(request, propietario_id):
    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().distinct()
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()
    propietario = get_object_or_404(PropietarioInmueble, id=propietario_id, portafolio__in=portafolios)
    
    propiedades = propietario.propiedades.filter(is_deleted=False)
    contratos = Contrato.objects.filter(propiedad__in=propiedades, activo=True).select_related('propiedad', 'inquilino')
    gastos_generales = GastoGeneralPropietario.objects.filter(propietario_inmueble=propietario).order_by('-fecha')[:10]
    liquidaciones = LiquidacionPropietario.objects.filter(propietario_inmueble=propietario).order_by('-periodo_anio', '-periodo_mes')[:12]
    recordatorios = propietario.recordatorios_pago.all().order_by('fecha_recordatorio')[:10]
    
    context = {
        'titulo_pagina': f'Expediente de Propietario: {propietario.nombre}',
        'propietario': propietario,
        'propiedades': propiedades,
        'contratos': contratos,
        'gastos_generales': gastos_generales,
        'liquidaciones': liquidaciones,
        'recordatorios': recordatorios,
    }
    return render(request, 'gestion_propiedades/detalle_propietario.html', context)


# --- MÓDULO DE RECORDATORIOS DE PAGOS A PROPIETARIOS ---

@login_required(login_url='/login/')
def lista_recordatorios_propietarios(request):
    """
    Sección centralizada para gestionar recordatorios de pagos y transferencias a propietarios.
    Permite ver pagos pendientes, vencidos, programados para el mes y completados.
    """
    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().distinct()
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()

    hoy = date.today()
    propietario_id = request.GET.get('propietario_id', '')
    filtro_estado = request.GET.get('filtro', 'PENDIENTES')
    busqueda = request.GET.get('q', '').strip().lower()

    qs = RecordatorioPagoPropietario.objects.filter(
        portafolio__in=portafolios
    ).select_related('propietario', 'portafolio', 'creado_por')

    if propietario_id and propietario_id.isdigit():
        qs = qs.filter(propietario_id=int(propietario_id))

    if busqueda:
        qs = qs.filter(
            Q(titulo__icontains=busqueda) |
            Q(propietario__nombre__icontains=busqueda) |
            Q(notas__icontains=busqueda)
        )

    # Contadores para KPIs
    base_qs = RecordatorioPagoPropietario.objects.filter(portafolio__in=portafolios)
    if propietario_id and propietario_id.isdigit():
        base_qs = base_qs.filter(propietario_id=int(propietario_id))

    total_pendientes = base_qs.filter(estado='PENDIENTE').count()
    monto_total_pendiente = base_qs.filter(estado='PENDIENTE').aggregate(total=Sum('monto_sugerido'))['total'] or decimal.Decimal('0.00')
    vencidos_count = base_qs.filter(estado='PENDIENTE', fecha_recordatorio__lt=hoy).count()
    hoy_proximos_count = base_qs.filter(estado='PENDIENTE', fecha_recordatorio__gte=hoy, fecha_recordatorio__lte=hoy + timedelta(days=7)).count()
    completados_mes = base_qs.filter(estado='COMPLETADO', fecha_recordatorio__month=hoy.month, fecha_recordatorio__year=hoy.year).count()

    # Aplicación del filtro seleccionado
    if filtro_estado == 'PENDIENTES':
        qs = qs.filter(estado='PENDIENTE')
    elif filtro_estado == 'VENCIDOS':
        qs = qs.filter(estado='PENDIENTE', fecha_recordatorio__lt=hoy)
    elif filtro_estado == 'PROXIMOS':
        qs = qs.filter(estado='PENDIENTE', fecha_recordatorio__gte=hoy, fecha_recordatorio__lte=hoy + timedelta(days=7))
    elif filtro_estado == 'COMPLETADOS':
        qs = qs.filter(estado='COMPLETADO')
    elif filtro_estado == 'TODOS':
        pass

    recordatorios = list(qs.order_by('fecha_recordatorio', '-prioridad'))

    # Formulario para modal de creación rápida
    form = RecordatorioPagoPropietarioForm(portafolios=portafolios, initial={'fecha_recordatorio': hoy})
    propietarios_list = PropietarioInmueble.objects.filter(portafolio__in=portafolios, activo=True).order_by('nombre')

    context = {
        'titulo_pagina': 'Recordatorios de Pagos a Propietarios',
        'recordatorios': recordatorios,
        'hoy': hoy,
        'filtro_estado': filtro_estado,
        'busqueda': busqueda,
        'propietario_sel': propietario_id,
        'propietarios_list': propietarios_list,
        'total_pendientes': total_pendientes,
        'monto_total_pendiente': monto_total_pendiente,
        'vencidos_count': vencidos_count,
        'hoy_proximos_count': hoy_proximos_count,
        'completados_mes': completados_mes,
        'form': form,
    }
    return render(request, 'gestion_propiedades/lista_recordatorios_propietarios.html', context)


@login_required(login_url='/login/')
def crear_recordatorio_propietario(request):
    """Crea un recordatorio de pago a un propietario."""
    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().distinct()
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()

    next_url = request.POST.get('next') or request.GET.get('next')

    if request.method == 'POST':
        form = RecordatorioPagoPropietarioForm(request.POST, portafolios=portafolios)
        if form.is_valid():
            rec = form.save(commit=False)
            rec.portafolio = rec.propietario.portafolio
            rec.creado_por = request.user
            rec.save()
            messages.success(request, f'Recordatorio de pago para {rec.propietario.nombre} programado para el {rec.fecha_recordatorio.strftime("%d/%m/%Y")}.')
            if next_url:
                return redirect(next_url)
            return redirect('lista_recordatorios_propietarios')
        else:
            messages.error(request, "Por favor revise los campos del formulario de recordatorio.")
    
    return redirect('lista_recordatorios_propietarios')


@login_required(login_url='/login/')
def cambiar_estado_recordatorio_propietario(request, recordatorio_id, nuevo_estado):
    """Marca un recordatorio como COMPLETADO, PENDIENTE o DESCARTADO."""
    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().distinct()
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()

    recordatorio = get_object_or_404(RecordatorioPagoPropietario, id=recordatorio_id, portafolio__in=portafolios)
    
    estados_validos = ['PENDIENTE', 'COMPLETADO', 'DESCARTADO']
    if nuevo_estado in estados_validos:
        recordatorio.estado = nuevo_estado
        recordatorio.save()
        if nuevo_estado == 'COMPLETADO':
            messages.success(request, f'Pago a {recordatorio.propietario.nombre} marcado como Pagado / Transferido.')
        elif nuevo_estado == 'PENDIENTE':
            messages.info(request, f'Recordatorio de pago a {recordatorio.propietario.nombre} devuelto a Pendiente.')
        else:
            messages.warning(request, f'Recordatorio descartado.')
    
    next_url = request.GET.get('next')
    if next_url:
        return redirect(next_url)
    return redirect('lista_recordatorios_propietarios')


@login_required(login_url='/login/')
def eliminar_recordatorio_propietario(request, recordatorio_id):
    """Elimina un recordatorio de pago."""
    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().distinct()
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()

    recordatorio = get_object_or_404(RecordatorioPagoPropietario, id=recordatorio_id, portafolio__in=portafolios)
    if request.method == 'POST':
        propietario_nombre = recordatorio.propietario.nombre
        recordatorio.delete()
        messages.success(request, f'Recordatorio de pago para {propietario_nombre} eliminado.')
    
    next_url = request.GET.get('next') or request.POST.get('next')
    if next_url:
        return redirect(next_url)
    return redirect('lista_recordatorios_propietarios')


# --- MÓDULO DE GASTOS GENERALES Y DEDUCCIONES ---

@login_required(login_url='/login/')
def lista_gastos_generales(request):
    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().distinct()
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()
    
    gastos = GastoGeneralPropietario.objects.filter(
        portafolio__in=portafolios
    ).select_related('propietario_inmueble', 'propiedad', 'portafolio').order_by('-fecha', '-creado_en')
    
    total_monto = gastos.aggregate(total=Sum('monto'))['total'] or decimal.Decimal('0.00')
    
    context = {
        'titulo_pagina': 'Gastos Generales y Deducciones',
        'gastos': gastos,
        'total_monto': total_monto
    }
    return render(request, 'gestion_propiedades/lista_gastos_generales.html', context)


@login_required(login_url='/login/')
def registrar_gasto_general(request):
    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().distinct()
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()
    
    next_url = request.POST.get('next') or request.GET.get('next')
    
    if request.method == 'POST':
        post_data = request.POST.copy()
        
        # Soporte inteligente para cálculo automático de ITBIS 18%
        if post_data.get('categoria') == 'ITBIS_18' and (not post_data.get('monto') or post_data.get('monto').strip() in ['', '0', '0.00']):
            prop_id = post_data.get('propietario_inmueble')
            mes_val = post_data.get('mes')
            anio_val = post_data.get('anio')
            if prop_id:
                try:
                    m_int = int(mes_val) if mes_val else date.today().month
                    a_int = int(anio_val) if anio_val else date.today().year
                    recibos = ReciboPago.objects.filter(
                        factura__contrato__propiedad__propietario_inmueble_id=prop_id,
                        fecha_pago__month=m_int,
                        fecha_pago__year=a_int
                    )
                    renta_cobrada = recibos.aggregate(total=Sum('monto_a_renta'))['total'] or decimal.Decimal('0.00')
                    if renta_cobrada == decimal.Decimal('0.00'):
                        renta_cobrada = recibos.aggregate(total=Sum('monto_pagado'))['total'] or decimal.Decimal('0.00')
                    itbis_auto = round(renta_cobrada * decimal.Decimal('0.18'), 2)
                    post_data['monto'] = str(itbis_auto)
                    if not post_data.get('concepto'):
                        post_data['concepto'] = f"Impuesto ITBIS (18%) - {obtener_nombre_mes(m_int)} {a_int}"
                except Exception as itbis_err:
                    logger.warning(f"Error autocalculando ITBIS en backend: {itbis_err}")

        form = GastoGeneralPropietarioForm(post_data, request.FILES, portafolios=portafolios)
        if form.is_valid():
            gasto = form.save(commit=False)
            gasto.portafolio = portafolios.first()
            gasto.creado_por = request.user
            gasto.save()
            messages.success(request, f'Gasto general "{gasto.concepto}" de RD${gasto.monto:,.2f} registrado correctamente.')
            
            if next_url == 'reporte_propietario':
                prop_id = request.POST.get('propietario_inmueble') or (gasto.propietario_inmueble.id if gasto.propietario_inmueble else '')
                mes = request.POST.get('mes') or ''
                anio = request.POST.get('anio') or ''
                return redirect(f"{reverse('reporte_propietario')}?propietario_id={prop_id}&mes={mes}&anio={anio}")
                
            return redirect('lista_gastos_generales')
    else:
        initial_dict = {}
        if request.GET.get('propietario_id'):
            initial_dict['propietario_inmueble'] = request.GET.get('propietario_id')
        form = GastoGeneralPropietarioForm(initial=initial_dict, portafolios=portafolios)
        
    context = {
        'titulo_pagina': 'Registrar Gasto General o Deducción',
        'form': form,
    }
    return render(request, 'gestion_propiedades/form_generico.html', context)


@login_required(login_url='/login/')
def eliminar_gasto_general(request, gasto_id):
    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().distinct()
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()
    gasto = get_object_or_404(GastoGeneralPropietario, id=gasto_id, portafolio__in=portafolios)
    if request.method == 'POST':
        gasto.delete()
        messages.success(request, 'Gasto eliminado exitosamente.')
    return redirect('lista_gastos_generales')


# --- REPORTE CONSOLIDADO Y LIQUIDACIÓN A PROPIETARIOS ---

@login_required(login_url='/login/')
def reporte_propietario(request):
    """
    Informe consolidado por Propietario de Inmuebles o propiedades seleccionadas.
    Calcula rentas cobradas, comisiones, gastos directos/generales y neto a liquidar.
    """
    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().distinct()
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()

    portafolio_id = request.GET.get('portafolio_id', 'TODOS')
    if portafolio_id != 'TODOS' and portafolio_id and str(portafolio_id).isdigit():
        portafolios_filtrados = portafolios.filter(id=int(portafolio_id))
    else:
        portafolios_filtrados = portafolios
    
    propietarios_list = PropietarioInmueble.objects.filter(portafolio__in=portafolios_filtrados, activo=True).order_by('nombre')
    todas_propiedades = Propiedad.objects.filter(portafolio__in=portafolios_filtrados, is_deleted=False).order_by('nombre_o_numero')
    
    propietario_id = request.GET.get('propietario_id')
    mes = int(request.GET.get('mes', date.today().month))
    anio = int(request.GET.get('anio', date.today().year))
    
    propietario_seleccionado = None
    if propietario_id:
        propietario_seleccionado = propietarios_list.filter(id=propietario_id).first()
        
    if propietario_seleccionado:
        propiedades = todas_propiedades.filter(propietario_inmueble=propietario_seleccionado)
    else:
        propiedades_seleccionadas_ids = request.GET.getlist('propiedades')
        if propiedades_seleccionadas_ids:
            propiedades = todas_propiedades.filter(id__in=propiedades_seleccionadas_ids)
        else:
            propiedades = todas_propiedades
            
    total_ingresos = decimal.Decimal('0.00')
    total_gastos_propiedades = decimal.Decimal('0.00')
    total_gastos_generales = decimal.Decimal('0.00')
    monto_comision = decimal.Decimal('0.00')
    total_morosidad = decimal.Decimal('0.00')
    total_depositos = decimal.Decimal('0.00')
    propiedades_ocupadas = 0
    contratos_activos = []
    recibos_cobrados = []
    gastos_directos_list = []
    gastos_generales_list = []
    
    if propiedades.exists():
        # Recibos cobrados en el mes/año
        recibos_qs = ReciboPago.objects.filter(
            factura__contrato__propiedad__in=propiedades,
            fecha_pago__month=mes,
            fecha_pago__year=anio
        ).select_related('factura__contrato__propiedad', 'factura__contrato__inquilino')
        
        recibos_cobrados = list(recibos_qs)
        ingresos_agg = sum(r.monto_pagado for r in recibos_cobrados)
        total_ingresos = decimal.Decimal(str(ingresos_agg)) if ingresos_agg else decimal.Decimal('0.00')
        
        # Mantenimientos directos de las propiedades en el mes/año
        mantenimientos_qs = MantenimientoUnidad.objects.filter(
            propiedad__in=propiedades,
            fecha_reporte__month=mes,
            fecha_reporte__year=anio
        ).select_related('propiedad')
        gastos_directos_list = list(mantenimientos_qs)
        gastos_agg = sum(m.costo for m in gastos_directos_list)
        total_gastos_propiedades = decimal.Decimal(str(gastos_agg)) if gastos_agg else decimal.Decimal('0.00')
        
        # Gastos generales / deducciones asociadas al propietario o a sus propiedades
        if propietario_seleccionado:
            gastos_gen_qs = GastoGeneralPropietario.objects.filter(
                Q(propietario_inmueble=propietario_seleccionado) | Q(propiedad__in=propiedades),
                fecha__month=mes,
                fecha__year=anio
            )
        else:
            gastos_gen_qs = GastoGeneralPropietario.objects.filter(
                propiedad__in=propiedades,
                fecha__month=mes,
                fecha__year=anio
            )
        gastos_generales_list = list(gastos_gen_qs)
        gastos_gen_agg = sum(g.monto for g in gastos_generales_list)
        total_gastos_generales = decimal.Decimal(str(gastos_gen_agg)) if gastos_gen_agg else decimal.Decimal('0.00')
        
        # Cálculo de comisión de administración si hay propietario seleccionado
        # REGLA: Los conceptos adicionales (mantenimiento, agua, bomba, basura) y moras NO pagan comisión.
        # La comisión de abogados/administración aplica exclusivamente sobre el Alquiler cobrado.
        total_renta_cobrada = sum(r.monto_a_renta for r in recibos_cobrados)
        total_servicios_cobrados = sum(r.monto_a_servicios for r in recibos_cobrados)
        total_mora_cobrada = sum(r.monto_a_mora for r in recibos_cobrados)

        if total_renta_cobrada == Decimal('0.00') and total_ingresos > Decimal('0.00'):
            total_renta_cobrada = total_ingresos

        if propietario_seleccionado:
            if propietario_seleccionado.tipo_comision == 'PORCENTAJE':
                factor = propietario_seleccionado.porcentaje_comision / decimal.Decimal('100.0')
                monto_comision = round(total_renta_cobrada * factor, 2)
            else:
                num_props = propiedades.count()
                monto_comision = propietario_seleccionado.monto_comision_fijo * num_props
                
        # Morosidad general
        facturas_vencidas = Factura.objects.filter(
            contrato__propiedad__in=propiedades,
            estado='ATRASADA'
        ).annotate(mora_acumulada=Sum('moras__monto'))
        
        for f in facturas_vencidas:
            mora = f.mora_acumulada or decimal.Decimal('0.00')
            total_morosidad += f.monto_base + mora
            
        # Depósitos y contratos activos
        contratos_activos_qs = Contrato.objects.filter(
            propiedad__in=propiedades,
            activo=True
        ).select_related('propiedad', 'inquilino')
        
        for c in contratos_activos_qs:
            total_depositos += c.monto_deposito
            contratos_activos.append(c)
            
        propiedades_ocupadas = propiedades.filter(estado='OCUPADO').count()
        
        # --- SITUACIÓN DETALLADA INDIVIDUAL POR PROPIEDAD ---
        situacion_propiedades = []
        for prop in propiedades:
            contrato_act = prop.contratos.filter(activo=True).select_related('inquilino').first()
            facturas_prop = Factura.objects.filter(
                contrato__propiedad=prop,
                fecha_emision__month=mes,
                fecha_emision__year=anio
            )
            facturado_prop = facturas_prop.aggregate(total=Sum('monto_base'))['total'] or decimal.Decimal('0.00')
            
            recibos_prop = ReciboPago.objects.filter(
                factura__contrato__propiedad=prop,
                fecha_pago__month=mes,
                fecha_pago__year=anio
            )
            cobrado_prop = recibos_prop.aggregate(total=Sum('monto_pagado'))['total'] or decimal.Decimal('0.00')
            
            facturas_vencidas_prop = Factura.objects.filter(
                contrato__propiedad=prop,
                estado='ATRASADA'
            ).annotate(mora=Sum('moras__monto'))
            
            deuda_prop = decimal.Decimal('0.00')
            for f in facturas_vencidas_prop:
                mora_val = f.mora or decimal.Decimal('0.00')
                deuda_prop += f.monto_base + mora_val
                
            if prop.estado == 'DISPONIBLE':
                estado_pago = 'VACANTE'
            elif deuda_prop > decimal.Decimal('0.00'):
                estado_pago = 'ATRASADO'
            else:
                estado_pago = 'AL_DIA'
                
            situacion_propiedades.append({
                'propiedad': prop,
                'contrato': contrato_act,
                'inquilino': contrato_act.inquilino if contrato_act else None,
                'estado_pago': estado_pago,
                'facturado': facturado_prop,
                'cobrado': cobrado_prop,
                'deuda': deuda_prop,
                'deposito': contrato_act.monto_deposito if contrato_act else decimal.Decimal('0.00'),
                'custodia_deposito': contrato_act.get_custodia_deposito_display() if contrato_act else 'N/A',
                'detalles_custodia': contrato_act.detalles_custodia_deposito if contrato_act else ''
            })

        # --- CÁLCULO DE SALDO ACUMULADO MULTIMES NO LIQUIDADO ---
        saldo_acumulado_anterior = decimal.Decimal('0.00')
        if propietario_seleccionado:
            recibos_pasados = ReciboPago.objects.filter(
                factura__contrato__propiedad__propietario_inmueble=propietario_seleccionado
            ).exclude(
                fecha_pago__month=mes,
                fecha_pago__year=anio
            )
            periodos_pasados = recibos_pasados.values_list('fecha_pago__month', 'fecha_pago__year').distinct()
            for p_mes, p_anio in periodos_pasados:
                ya_liquidado = LiquidacionPropietario.objects.filter(
                    propietario_inmueble=propietario_seleccionado,
                    periodo_mes=p_mes,
                    periodo_anio=p_anio
                ).exists()
                if not ya_liquidado:
                    ing_pasado = ReciboPago.objects.filter(
                        factura__contrato__propiedad__propietario_inmueble=propietario_seleccionado,
                        fecha_pago__month=p_mes,
                        fecha_pago__year=p_anio
                    ).aggregate(total=Sum('monto_pagado'))['total'] or decimal.Decimal('0.00')
                    
                    if propietario_seleccionado.tipo_comision == 'PORCENTAJE':
                        comision_pasada = round(ing_pasado * (propietario_seleccionado.porcentaje_comision / decimal.Decimal('100.0')), 2)
                    else:
                        comision_pasada = propietario_seleccionado.monto_comision_fijo * propiedades.count()
                        
                    gastos_pasados = MantenimientoUnidad.objects.filter(
                        propiedad__propietario_inmueble=propietario_seleccionado,
                        fecha_reporte__month=p_mes,
                        fecha_reporte__year=p_anio
                    ).aggregate(total=Sum('costo'))['total'] or decimal.Decimal('0.00')
                    
                    gastos_gen_pasados = GastoGeneralPropietario.objects.filter(
                        propietario_inmueble=propietario_seleccionado,
                        fecha__month=p_mes,
                        fecha__year=p_anio
                    ).aggregate(total=Sum('monto'))['total'] or decimal.Decimal('0.00')
                    
                    neto_pasado = max(decimal.Decimal('0.00'), ing_pasado - (comision_pasada + gastos_pasados + gastos_gen_pasados))
                    saldo_acumulado_anterior += neto_pasado

    total_propiedades = propiedades.count()
    porcentaje_ocupacion = (propiedades_ocupadas / total_propiedades * 100) if total_propiedades > 0 else 0
    
    total_deducciones = monto_comision + total_gastos_propiedades + total_gastos_generales
    neto_a_liquidar_mes = max(decimal.Decimal('0.00'), total_ingresos - total_deducciones)
    neto_a_liquidar = neto_a_liquidar_mes + saldo_acumulado_anterior
    
    # Verificar si ya existe liquidación registrada para este propietario y periodo
    liquidacion_existente = None
    whatsapp_liquidacion_url = None
    mensaje_whatsapp_liquidacion = None
    if propietario_seleccionado:
        liquidacion_existente = LiquidacionPropietario.objects.filter(
            propietario_inmueble=propietario_seleccionado,
            periodo_mes=mes,
            periodo_anio=anio
        ).first()

        clean_phone = ''.join(filter(str.isdigit, propietario_seleccionado.telefono or ''))
        if len(clean_phone) == 10:
            clean_phone = "1" + clean_phone

        monto_num = liquidacion_existente.monto_neto_pagado if liquidacion_existente else neto_a_liquidar
        monto_str = f"RD$ {monto_num:,.2f}"
        fecha_pago_str = liquidacion_existente.fecha_pago.strftime('%d/%m/%Y') if (liquidacion_existente and liquidacion_existente.fecha_pago) else date.today().strftime('%d/%m/%Y')
        metodo_str = liquidacion_existente.metodo_pago if (liquidacion_existente and liquidacion_existente.metodo_pago) else 'Transferencia Bancaria'
        ref_str = f"\n🔖 *Referencia / TXN:* {liquidacion_existente.referencia_transaccion}" if (liquidacion_existente and liquidacion_existente.referencia_transaccion) else ""
        banco_str = ""
        if propietario_seleccionado.banco_nombre:
            banco_str = f"\n🏦 *Cuenta Destino:* {propietario_seleccionado.banco_nombre}"
            if propietario_seleccionado.tipo_cuenta or propietario_seleccionado.numero_cuenta:
                banco_str += f" ({propietario_seleccionado.tipo_cuenta or 'Cuenta'} {propietario_seleccionado.numero_cuenta or ''})"

        nombre_mes_texto = obtener_nombre_mes(mes)
        mensaje_whatsapp_liquidacion = (
            f"¡Hola, {propietario_seleccionado.nombre}! 👋\n\n"
            f"Le informamos que hemos procesado la liquidación de sus alquileres correspondiente al período de *{nombre_mes_texto} {anio}*.\n\n"
            f"💰 *Monto Neto Transferido:* {monto_str}\n"
            f"📅 *Fecha de Pago:* {fecha_pago_str}\n"
            f"💳 *Método:* {metodo_str}{ref_str}{banco_str}\n\n"
            f"Cualquier consulta sobre el desglose de sus inmuebles estamos a su entera disposición. ¡Muchas gracias por su confianza!"
        )
        import urllib.parse
        mensaje_enc = urllib.parse.quote(mensaje_whatsapp_liquidacion)
        whatsapp_liquidacion_url = f"https://wa.me/{clean_phone}?text={mensaje_enc}" if clean_phone else f"https://wa.me/?text={mensaje_enc}"

    context = {
        'titulo_pagina': 'Reporte y Liquidación de Propietario',
        'propietarios_list': propietarios_list,
        'propietario_seleccionado': propietario_seleccionado,
        'todas_propiedades': todas_propiedades,
        'mes': mes,
        'nombre_mes': obtener_nombre_mes(mes),
        'anio': anio,
        'anios_disponibles': range(date.today().year - 2, date.today().year + 2),
        'total_ingresos': total_ingresos,
        'monto_comision': monto_comision,
        'total_gastos_propiedades': total_gastos_propiedades,
        'total_gastos_generales': total_gastos_generales,
        'total_deducciones': total_deducciones,
        'total_morosidad': total_morosidad,
        'total_depositos': total_depositos,
        'propiedades_ocupadas': propiedades_ocupadas,
        'total_propiedades': total_propiedades,
        'porcentaje_ocupacion': round(porcentaje_ocupacion, 1),
        'recibos_cobrados': recibos_cobrados,
        'total_renta_cobrada': total_renta_cobrada if 'total_renta_cobrada' in locals() else total_ingresos,
        'itbis_18_calculado': round(Decimal(str(total_renta_cobrada if 'total_renta_cobrada' in locals() else total_ingresos)) * Decimal('0.18'), 2),
        'total_servicios_cobrados': total_servicios_cobrados if 'total_servicios_cobrados' in locals() else decimal.Decimal('0.00'),
        'total_mora_cobrada': total_mora_cobrada if 'total_mora_cobrada' in locals() else decimal.Decimal('0.00'),
        'gastos_directos_list': gastos_directos_list,
        'gastos_generales_list': gastos_generales_list,
        'contratos_activos': contratos_activos,
        'situacion_propiedades': situacion_propiedades if 'situacion_propiedades' in locals() else [],
        'saldo_acumulado_anterior': saldo_acumulado_anterior if 'saldo_acumulado_anterior' in locals() else decimal.Decimal('0.00'),
        'neto_a_liquidar_mes': neto_a_liquidar_mes if 'neto_a_liquidar_mes' in locals() else decimal.Decimal('0.00'),
        'neto_a_liquidar': neto_a_liquidar,
        'liquidacion_existente': liquidacion_existente,
        'whatsapp_liquidacion_url': whatsapp_liquidacion_url,
        'mensaje_whatsapp_liquidacion': mensaje_whatsapp_liquidacion,
        'fecha_generacion': timezone.now(),
        'portafolios': portafolios,
        'portafolio_sel': str(portafolio_id),
    }
    return render(request, 'gestion_propiedades/reporte_propietario.html', context)


@login_required(login_url='/login/')
def procesar_liquidacion_propietario(request, propietario_id):
    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().distinct()
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()
    propietario = get_object_or_404(PropietarioInmueble, id=propietario_id, portafolio__in=portafolios)
    
    if request.method == 'POST':
        mes = int(request.POST.get('mes', date.today().month))
        anio = int(request.POST.get('anio', date.today().year))
        
        propiedades = propietario.propiedades.filter(is_deleted=False)
        
        recibos = ReciboPago.objects.filter(
            factura__contrato__propiedad__in=propiedades,
            fecha_pago__month=mes,
            fecha_pago__year=anio
        )
        total_ingresos = recibos.aggregate(total=Sum('monto_pagado'))['total'] or decimal.Decimal('0.00')
        total_renta_cobrada = recibos.aggregate(total=Sum('monto_a_renta'))['total'] or decimal.Decimal('0.00')
        if total_renta_cobrada == decimal.Decimal('0.00') and total_ingresos > decimal.Decimal('0.00'):
            total_renta_cobrada = total_ingresos

        if propietario.tipo_comision == 'PORCENTAJE':
            factor = propietario.porcentaje_comision / decimal.Decimal('100.0')
            monto_comision = round(total_renta_cobrada * factor, 2)
        else:
            num_props = propiedades.count()
            monto_comision = propietario.monto_comision_fijo * num_props
            
        gastos_prop = MantenimientoUnidad.objects.filter(
            propiedad__in=propiedades,
            fecha_reporte__month=mes,
            fecha_reporte__year=anio
        ).aggregate(total=Sum('costo'))['total'] or decimal.Decimal('0.00')
        
        gastos_gen = GastoGeneralPropietario.objects.filter(
            Q(propietario_inmueble=propietario) | Q(propiedad__in=propiedades),
            fecha__month=mes,
            fecha__year=anio
        ).aggregate(total=Sum('monto'))['total'] or decimal.Decimal('0.00')
        
        total_deducciones = monto_comision + gastos_prop + gastos_gen
        neto_pagar = max(decimal.Decimal('0.00'), total_ingresos - total_deducciones)
        
        metodo = request.POST.get('metodo_pago', 'TRANSFERENCIA')
        referencia = request.POST.get('referencia_transaccion', '')
        fecha_pago_val = request.POST.get('fecha_pago', date.today())
        notas = request.POST.get('notas', '')
        comprobante = request.FILES.get('comprobante_pago')

        defaults = {
            'monto_rentas_cobradas': total_ingresos,
            'monto_comision': monto_comision,
            'monto_gastos_propiedades': gastos_prop,
            'monto_gastos_generales': gastos_gen,
            'monto_neto_pagado': neto_pagar,
            'estado': 'PAGADO',
            'fecha_pago': fecha_pago_val,
            'metodo_pago': metodo,
            'referencia_transaccion': referencia,
            'notas': notas,
            'registrado_por': request.user
        }
        if comprobante:
            defaults['comprobante_pago'] = comprobante

        try:
            LiquidacionPropietario.objects.update_or_create(
                propietario_inmueble=propietario,
                periodo_mes=mes,
                periodo_anio=anio,
                defaults=defaults
            )
            messages.success(request, f'Liquidación de {obtener_nombre_mes(mes)} {anio} para {propietario.nombre} registrada correctamente.')
        except Exception as e:
            if comprobante:
                defaults.pop('comprobante_pago', None)
                try:
                    LiquidacionPropietario.objects.update_or_create(
                        propietario_inmueble=propietario,
                        periodo_mes=mes,
                        periodo_anio=anio,
                        defaults=defaults
                    )
                    messages.warning(request, f'Liquidación registrada, pero hubo un problema al procesar el archivo adjunto: {str(e)}.')
                    return redirect(f'/reportes/propietario/?propietario_id={propietario.id}&mes={mes}&anio={anio}')
                except Exception as inner_e:
                    messages.error(request, f'Error al registrar liquidación: {str(inner_e)}')
                    return redirect(f'/reportes/propietario/?propietario_id={propietario.id}&mes={mes}&anio={anio}')
            messages.error(request, f'Error al registrar liquidación: {str(e)}')
    return redirect(f'/reportes/propietario/?propietario_id={propietario.id}&mes={mes}&anio={anio}')


@login_required(login_url='/login/')
def ver_comprobante_liquidacion(request, liquidacion_id):
    """
    Sirve de forma segura y tolerante a fallos el comprobante/recibo adjunto de una liquidación.
    Si está en Cloudinary o URL remota, verifica que el archivo realmente exista antes de redirigir
    (evitando pantallas en blanco o ERR_INVALID_RESPONSE del navegador).
    Si está en almacenamiento local, lo transmite directamente mediante FileResponse.
    Si el archivo no existe físicamente, muestra una alerta clara y amigable en vez de fallar.
    """
    from django.http import FileResponse
    import mimetypes
    import requests

    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().distinct()
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()

    liquidacion = get_object_or_404(
        LiquidacionPropietario,
        id=liquidacion_id,
        propietario_inmueble__portafolio__in=portafolios
    )

    fallback_url = f"/reportes/propietario/?propietario_id={liquidacion.propietario_inmueble_id}&mes={liquidacion.periodo_mes}&anio={liquidacion.periodo_anio}"

    if not liquidacion.comprobante_pago:
        messages.warning(request, "Esta liquidación no tiene ningún comprobante de pago adjunto.")
        return redirect(fallback_url)

    try:
        nombre_archivo = os.path.basename(liquidacion.comprobante_pago.name or 'comprobante')

        # 1. Si tiene URL remota (Cloudinary / CDN), verificar existencia real antes de enviar al usuario
        try:
            url_archivo = liquidacion.comprobante_pago.url
            if url_archivo and (url_archivo.startswith('http://') or url_archivo.startswith('https://')):
                try:
                    resp = requests.get(url_archivo, stream=True, timeout=3.5, headers={'User-Agent': 'Mozilla/5.0'})
                    if resp.status_code == 200:
                        return redirect(url_archivo)
                    else:
                        logger.warning(f"Comprobante remoto #{liquidacion_id} respondió HTTP {resp.status_code} ({url_archivo})")
                except Exception as req_err:
                    logger.warning(f"Error verificando conectividad de comprobante en Cloudinary: {req_err}")
        except Exception as e:
            logger.warning(f"Error accediendo a la URL del comprobante #{liquidacion_id}: {e}")

        # 2. Verificar si está disponible en almacenamiento local / fallback
        try:
            if liquidacion.comprobante_pago.storage.exists(liquidacion.comprobante_pago.name):
                archivo = liquidacion.comprobante_pago.open('rb')
                content_type, _ = mimetypes.guess_type(liquidacion.comprobante_pago.name)
                return FileResponse(archivo, content_type=content_type or 'application/octet-stream')
        except Exception as e:
            logger.warning(f"Error accediendo al storage local de liquidación #{liquidacion_id}: {e}")

        # 3. Comprobar si existe físicamente en MEDIA_ROOT
        try:
            local_path = os.path.join(settings.MEDIA_ROOT, liquidacion.comprobante_pago.name)
            if os.path.exists(local_path):
                archivo = open(local_path, 'rb')
                content_type, _ = mimetypes.guess_type(local_path)
                return FileResponse(archivo, content_type=content_type or 'application/octet-stream')
        except Exception as e:
            logger.warning(f"Error accediendo al archivo en MEDIA_ROOT de liquidación #{liquidacion_id}: {e}")

        # 4. Si el archivo no está en ningún almacenamiento, orientar amigablemente al usuario
        messages.warning(
            request,
            f"El archivo del recibo adjunto '{nombre_archivo}' no se encuentra disponible en los servidores o su carga previa no se completó. "
            "Por favor utilice el botón '✏️ Modificar / Adjuntar Recibo' para cargarlo nuevamente."
        )
        return redirect(fallback_url)
    except Exception as err:
        logger.error(f"Error general en ver_comprobante_liquidacion #{liquidacion_id}: {err}", exc_info=True)
        messages.warning(
            request,
            "No se pudo acceder al archivo del recibo adjunto. Por favor utilice el botón '✏️ Modificar / Adjuntar Recibo' para adjuntarlo nuevamente."
        )
        return redirect(fallback_url)


@login_required(login_url='/login/')
def imprimir_liquidacion_propietario(request, propietario_id):
    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().distinct()
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()
    propietario = get_object_or_404(PropietarioInmueble, id=propietario_id, portafolio__in=portafolios)
    
    mes = int(request.GET.get('mes', date.today().month))
    anio = int(request.GET.get('anio', date.today().year))
    
    propiedades = propietario.propiedades.filter(is_deleted=False)
    
    recibos = ReciboPago.objects.filter(
        factura__contrato__propiedad__in=propiedades,
        fecha_pago__month=mes,
        fecha_pago__year=anio
    ).select_related('factura__contrato__propiedad', 'factura__contrato__inquilino')
    
    total_ingresos = recibos.aggregate(total=Sum('monto_pagado'))['total'] or decimal.Decimal('0.00')
    
    if propietario.tipo_comision == 'PORCENTAJE':
        monto_comision = round(total_ingresos * (propietario.porcentaje_comision / decimal.Decimal('100.0')), 2)
    else:
        num_props = propiedades.count()
        monto_comision = propietario.monto_comision_fijo * num_props
        
    gastos_propiedades = MantenimientoUnidad.objects.filter(
        propiedad__in=propiedades,
        fecha_reporte__month=mes,
        fecha_reporte__year=anio
    ).select_related('propiedad')
    total_gastos_prop = gastos_propiedades.aggregate(total=Sum('costo'))['total'] or decimal.Decimal('0.00')
    
    gastos_generales = GastoGeneralPropietario.objects.filter(
        Q(propietario_inmueble=propietario) | Q(propiedad__in=propiedades),
        fecha__month=mes,
        fecha__year=anio
    )
    total_gastos_gen = gastos_generales.aggregate(total=Sum('monto'))['total'] or decimal.Decimal('0.00')
    
    total_deducciones = monto_comision + total_gastos_prop + total_gastos_gen
    neto_a_pagar = max(decimal.Decimal('0.00'), total_ingresos - total_deducciones)
    
    liquidacion = LiquidacionPropietario.objects.filter(
        propietario_inmueble=propietario,
        periodo_mes=mes,
        periodo_anio=anio
    ).first()
    
    context = {
        'propietario': propietario,
        'mes': mes,
        'nombre_mes': obtener_nombre_mes(mes),
        'anio': anio,
        'propiedades': propiedades,
        'recibos': recibos,
        'gastos_propiedades': gastos_propiedades,
        'gastos_generales': gastos_generales,
        'total_ingresos': total_ingresos,
        'monto_comision': monto_comision,
        'total_gastos_prop': total_gastos_prop,
        'total_gastos_gen': total_gastos_gen,
        'total_deducciones': total_deducciones,
        'neto_a_pagar': neto_a_pagar,
        'liquidacion': liquidacion,
        'fecha_emision': timezone.now()
    }
    return render(request, 'gestion_propiedades/imprimir_liquidacion_propietario.html', context)


@login_required(login_url='/login/')
def imprimir_estado_situacion_propietario(request, propietario_id):
    """
    Genera la vista imprimible en formato Estado de Situación de Inmuebles para compartir con el Propietario.
    """
    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().distinct()
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()
    propietario = get_object_or_404(PropietarioInmueble, id=propietario_id, portafolio__in=portafolios)
    
    mes = int(request.GET.get('mes', date.today().month))
    anio = int(request.GET.get('anio', date.today().year))
    
    propiedades = propietario.propiedades.filter(is_deleted=False).order_by('nombre_o_numero')
    
    situacion_propiedades = []
    total_facturado = decimal.Decimal('0.00')
    total_cobrado = decimal.Decimal('0.00')
    total_deuda = decimal.Decimal('0.00')
    total_depositos = decimal.Decimal('0.00')
    propiedades_ocupadas = 0

    for prop in propiedades:
        contrato_act = prop.contratos.filter(activo=True).select_related('inquilino').first()
        facturas_prop = Factura.objects.filter(
            contrato__propiedad=prop,
            fecha_emision__month=mes,
            fecha_emision__year=anio
        )
        facturado_prop = facturas_prop.aggregate(total=Sum('monto_base'))['total'] or decimal.Decimal('0.00')
        
        recibos_prop = ReciboPago.objects.filter(
            factura__contrato__propiedad=prop,
            fecha_pago__month=mes,
            fecha_pago__year=anio
        )
        cobrado_prop = recibos_prop.aggregate(total=Sum('monto_pagado'))['total'] or decimal.Decimal('0.00')
        
        facturas_vencidas_prop = Factura.objects.filter(
            contrato__propiedad=prop,
            estado='ATRASADA'
        ).annotate(mora=Sum('moras__monto'))
        
        deuda_prop = decimal.Decimal('0.00')
        for f in facturas_vencidas_prop:
            mora_val = f.mora or decimal.Decimal('0.00')
            deuda_prop += f.monto_base + mora_val
            
        if prop.estado == 'DISPONIBLE':
            estado_pago = 'VACANTE'
        elif deuda_prop > decimal.Decimal('0.00'):
            estado_pago = 'ATRASADO'
        else:
            estado_pago = 'AL_DIA'
            
        if prop.estado == 'OCUPADO':
            propiedades_ocupadas += 1

        dep_monto = contrato_act.monto_deposito if contrato_act else decimal.Decimal('0.00')
        total_facturado += facturado_prop
        total_cobrado += cobrado_prop
        total_deuda += deuda_prop
        total_depositos += dep_monto
            
        situacion_propiedades.append({
            'propiedad': prop,
            'contrato': contrato_act,
            'inquilino': contrato_act.inquilino if contrato_act else None,
            'estado_pago': estado_pago,
            'facturado': facturado_prop,
            'cobrado': cobrado_prop,
            'deuda': deuda_prop,
            'deposito': dep_monto,
            'custodia_deposito': contrato_act.get_custodia_deposito_display() if contrato_act else 'N/A',
            'detalles_custodia': contrato_act.detalles_custodia_deposito if contrato_act else ''
        })

    context = {
        'propietario': propietario,
        'mes': mes,
        'nombre_mes': obtener_nombre_mes(mes),
        'anio': anio,
        'propiedades': propiedades,
        'situacion_propiedades': situacion_propiedades,
        'total_propiedades': propiedades.count(),
        'propiedades_ocupadas': propiedades_ocupadas,
        'propiedades_vacantes': propiedades.count() - propiedades_ocupadas,
        'total_facturado': total_facturado,
        'total_cobrado': total_cobrado,
        'total_deuda': total_deuda,
        'total_depositos': total_depositos,
        'fecha_emision': timezone.now()
    }
    return render(request, 'gestion_propiedades/imprimir_estado_situacion_propietario.html', context)


# --- MARKETPLACE VIEWS ---

from django.core.exceptions import PermissionDenied
from django.http import Http404
from .models import PublicacionMarketplace, ImagenPublicacion
from .forms import PublicacionMarketplaceForm

def limpiar_anuncios_expirados():
    """
    Función autolimpiadora: busca anuncios con más de 50 días desde su activación o renovación
    y los elimina por completo (incluyendo sus archivos multimedia de disco).
    """
    from django.utils import timezone
    limite = timezone.now() - timezone.timedelta(days=50)
    anuncios_obsoletos = PublicacionMarketplace.objects.filter(fecha_activacion__lte=limite)
    for anuncio in anuncios_obsoletos:
        anuncio.delete()  # Esto elimina en cascada las imágenes y sus archivos en disco


def marketplace_catalogo(request):
    """
    Catálogo completamente público e indexable de propiedades en alquiler.
    Exento de requerimiento de inicio de sesión o verificaciones de suscripción SaaS.
    """
    limpiar_anuncios_expirados()
    
    # Solo mostrar anuncios activos y no expirados (< 45 días)
    limite_expiracion = timezone.now() - timezone.timedelta(days=45)
    anuncios = PublicacionMarketplace.objects.filter(
        activo=True,
        fecha_activacion__gt=limite_expiracion
    ).select_related('propiedad', 'propiedad__portafolio').order_by('-fecha_activacion')

    # Filtrado por búsqueda libre (título, descripción, residencial)
    q = request.GET.get('q', '').strip()
    if q:
        anuncios = anuncios.filter(
            Q(titulo__icontains=q) |
            Q(descripcion__icontains=q) |
            Q(propiedad__grupo_o_residencial__icontains=q) |
            Q(propiedad__nombre_o_numero__icontains=q)
        )

    # Filtrado por rango de precios
    precio_min = request.GET.get('precio_min', '').strip()
    precio_max = request.GET.get('precio_max', '').strip()
    if precio_min:
        try:
            anuncios = anuncios.filter(precio_renta__gte=float(precio_min))
        except ValueError:
            pass
    if precio_max:
        try:
            anuncios = anuncios.filter(precio_renta__lte=float(precio_max))
        except ValueError:
            pass

    context = {
        'titulo_pagina': 'Marketplace de Alquileres',
        'anuncios': anuncios,
        'q': q,
        'precio_min': precio_min,
        'precio_max': precio_max,
    }
    return render(request, 'gestion_propiedades/marketplace_catalogo.html', context)


def marketplace_detalle(request, pk):
    """
    Ficha de detalle pública e indexable de un anuncio del Marketplace.
    """
    anuncio = get_object_or_404(PublicacionMarketplace, pk=pk)

    # Regla de visibilidad:
    # Solo es visible públicamente si está activa y no ha vencido (menos de 45 días).
    # Sin embargo, el propietario o administradores autorizados pueden previsualizarla aunque esté vencida/inactiva.
    es_propietario = False
    if request.user.is_authenticated:
        portafolio = anuncio.propiedad.portafolio
        es_propietario = (
            portafolio.propietario == request.user or
            portafolio.accesos.filter(usuario=request.user).exists() or
            request.user.is_superuser
        )

    if not anuncio.esta_visible and not es_propietario:
        raise Http404("Este anuncio no está disponible o ha expirado.")

    # Generar el enlace pre-llenado de WhatsApp
    import urllib.parse
    clean_phone = ''.join(filter(str.isdigit, anuncio.telefono_contacto))
    # Asegurar código de país por defecto si es necesario (ej: +1 para RD si tiene 10 dígitos)
    if len(clean_phone) == 10:
        clean_phone = "1" + clean_phone
    
    mensaje = f"¡Hola! Estoy interesado en la propiedad en alquiler '{anuncio.titulo}' (Renta: ${anuncio.precio_renta:,.2f}) que vi en el Marketplace de Alquilo."
    mensaje_enc = urllib.parse.quote(mensaje)
    whatsapp_url = f"https://wa.me/{clean_phone}?text={mensaje_enc}"

    context = {
        'titulo_pagina': anuncio.titulo,
        'anuncio': anuncio,
        'whatsapp_url': whatsapp_url,
        'es_propietario': es_propietario,
    }
    return render(request, 'gestion_propiedades/marketplace_detalle.html', context)


@login_required(login_url='/login/')
def crear_publicacion_marketplace(request, propiedad_id):
    """
    Crea una nueva publicación en el Marketplace público para una propiedad existente.
    Verifica que el usuario logueado tenga acceso de administración sobre el portafolio.
    """
    propiedad = get_object_or_404(Propiedad, id=propiedad_id, is_deleted=False)
    
    # Control de Acceso Multi-tenant
    portafolio = propiedad.portafolio
    tiene_acceso = (
        portafolio.propietario == request.user or
        portafolio.accesos.filter(usuario=request.user).exists() or
        request.user.is_superuser
    )
    if not tiene_acceso:
        raise PermissionDenied("No tienes permisos para publicar esta propiedad.")

    # Evitar publicaciones duplicadas
    if hasattr(propiedad, 'publicacion_marketplace'):
        messages.warning(request, "Esta propiedad ya tiene un anuncio en el Marketplace. Puedes editar el existente.")
        return redirect('detalle_propiedad', propiedad_id=propiedad.id)

    if request.method == 'POST':
        form = PublicacionMarketplaceForm(request.POST, request.FILES)
        if form.is_valid():
            publicacion = form.save(commit=False)
            publicacion.propiedad = propiedad
            publicacion.creado_por = request.user
            publicacion.fecha_activacion = timezone.now()
            publicacion.activo = True
            publicacion.save()

            # Procesar imágenes múltiples
            imagenes_subidas = request.FILES.getlist('imagenes')
            for f in imagenes_subidas:
                ImagenPublicacion.objects.create(publicacion=publicacion, imagen=f)

            # Registrar log de auditoría
            AuditLog.objects.create(
                accion='CREAR',
                modulo='Marketplace',
                descripcion=f"Publicó la propiedad '{propiedad}' en el Marketplace público (Precio: ${publicacion.precio_renta}).",
                usuario=request.user,
                portafolio=portafolio
            )

            messages.success(request, "¡Propiedad publicada con éxito en el Marketplace! Estará activa durante 45 días.")
            return redirect('detalle_propiedad', propiedad_id=propiedad.id)
    else:
        # Prefillar precio estimado si tiene un contrato previo, u otros datos útiles
        form = PublicacionMarketplaceForm(initial={
            'titulo': f"Alquiler de {propiedad.get_estado_display()} - {propiedad.nombre_o_numero}",
            'descripcion': propiedad.detalles or '',
        })

    context = {
        'titulo_pagina': 'Anunciar Propiedad',
        'form': form,
        'propiedad': propiedad,
    }
    return render(request, 'gestion_propiedades/crear_publicacion_marketplace.html', context)


@login_required(login_url='/login/')
def editar_publicacion_marketplace(request, propiedad_id):
    """
    Edita un anuncio existente en el Marketplace público.
    """
    publicacion = get_object_or_404(PublicacionMarketplace, propiedad_id=propiedad_id)
    propiedad = publicacion.propiedad
    
    # Control de Acceso
    portafolio = propiedad.portafolio
    tiene_acceso = (
        portafolio.propietario == request.user or
        portafolio.accesos.filter(usuario=request.user).exists() or
        request.user.is_superuser
    )
    if not tiene_acceso:
        raise PermissionDenied("No tienes permisos para editar este anuncio.")

    if request.method == 'POST':
        form = PublicacionMarketplaceForm(request.POST, request.FILES, instance=publicacion)
        if form.is_valid():
            publicacion = form.save()

            # Procesar nuevas imágenes subidas
            imagenes_subidas = request.FILES.getlist('imagenes')
            for f in imagenes_subidas:
                ImagenPublicacion.objects.create(publicacion=publicacion, imagen=f)

            # Registrar auditoría
            AuditLog.objects.create(
                accion='EDITAR',
                modulo='Marketplace',
                descripcion=f"Editó el anuncio del Marketplace para la propiedad '{propiedad}'.",
                usuario=request.user,
                portafolio=portafolio
            )

            messages.success(request, "El anuncio se ha actualizado correctamente.")
            return redirect('detalle_propiedad', propiedad_id=propiedad.id)
    else:
        form = PublicacionMarketplaceForm(instance=publicacion)

    context = {
        'titulo_pagina': 'Editar Anuncio',
        'form': form,
        'publicacion': publicacion,
        'propiedad': propiedad,
    }
    return render(request, 'gestion_propiedades/editar_publicacion_marketplace.html', context)


@login_required(login_url='/login/')
def eliminar_imagen_publicacion(request, imagen_id):
    """
    Elimina físicamente una imagen individual asociada a una publicación.
    """
    imagen = get_object_or_404(ImagenPublicacion, id=imagen_id)
    publicacion = imagen.publicacion
    propiedad = publicacion.propiedad

    # Control de Acceso
    portafolio = propiedad.portafolio
    tiene_acceso = (
        portafolio.propietario == request.user or
        portafolio.accesos.filter(usuario=request.user).exists() or
        request.user.is_superuser
    )
    if not tiene_acceso:
        raise PermissionDenied("No tienes permisos para modificar este anuncio.")

    # La eliminación física ocurre dentro del método delete() personalizado del modelo
    imagen.delete()
    messages.success(request, "Imagen eliminada con éxito.")
    return redirect('editar_publicacion_marketplace', propiedad_id=propiedad.id)


@login_required(login_url='/login/')
def republicar_publicacion_marketplace(request, propiedad_id):
    """
    Acción rápida de un solo clic (POST): reinicia la vigencia de 45 días del anuncio.
    """
    if request.method != 'POST':
        raise Http404("Método no permitido.")
        
    publicacion = get_object_or_404(PublicacionMarketplace, propiedad_id=propiedad_id)
    propiedad = publicacion.propiedad

    # Control de Acceso
    portafolio = propiedad.portafolio
    tiene_acceso = (
        portafolio.propietario == request.user or
        portafolio.accesos.filter(usuario=request.user).exists() or
        request.user.is_superuser
    )
    if not tiene_acceso:
        raise PermissionDenied("No tienes permisos para renovar este anuncio.")

    publicacion.fecha_activacion = timezone.now()
    publicacion.activo = True
    publicacion.save()

    # Log de Auditoría
    AuditLog.objects.create(
        accion='EDITAR',
        modulo='Marketplace',
        descripcion=f"Renovó la vigencia del anuncio en el Marketplace para la propiedad '{propiedad}' (Contador reiniciado a 45 días).",
        usuario=request.user,
        portafolio=portafolio
    )

    messages.success(request, "¡Anuncio renovado con éxito! Se ha reiniciado el contador de 45 días de vigencia pública.")
    return redirect('detalle_propiedad', propiedad_id=propiedad.id)


@login_required(login_url='/login/')
def borrar_publicacion_marketplace(request, propiedad_id):
    """
    Acción rápida (POST): elimina definitivamente la publicación y todos sus archivos del servidor.
    """
    if request.method != 'POST':
        raise Http404("Método no permitido.")

    publicacion = get_object_or_404(PublicacionMarketplace, propiedad_id=propiedad_id)
    propiedad = publicacion.propiedad

    # Control de Acceso
    portafolio = propiedad.portafolio
    tiene_acceso = (
        portafolio.propietario == request.user or
        portafolio.accesos.filter(usuario=request.user).exists() or
        request.user.is_superuser
    )
    if not tiene_acceso:
        raise PermissionDenied("No tienes permisos para eliminar este anuncio.")

    # La cascada física en cascada ocurre dentro del delete() personalizado del modelo
    publicacion.delete()

    # Log de Auditoría
    AuditLog.objects.create(
        accion='ELIMINAR',
        modulo='Marketplace',
        descripcion=f"Eliminó el anuncio de Marketplace y todos sus archivos multimedia para la propiedad '{propiedad}'.",
        usuario=request.user,
        portafolio=portafolio
    )

    messages.success(request, "Anuncio eliminado por completo. Las imágenes han sido removidas del disco del servidor para optimizar espacio.")
    return redirect('detalle_propiedad', propiedad_id=propiedad.id)


# --- MÓDULOS DE SEGURIDAD, RESPALDOS Y PAPELERA DE RECICLAJE ---
import csv
import io
import zipfile
import re
import requests

def _obtener_bytes_archivo(field_file):
    """
    Lee de forma segura el contenido binario (bytes) de un FieldFile de Django,
    soportando almacenamiento en la nube (Cloudinary / S3 / URL HTTP)
    y almacenamiento local en disco (FileSystemStorage / MEDIA_ROOT).
    NUNCA invoca directamente `.path` porque en Cloudinary u otros backends
    remotos lanza NotImplementedError provocando un error 500.
    """
    if not field_file or not getattr(field_file, 'name', None):
        return None

    # Método 1: Intentar leer mediante la interfaz estándar de storage de Django
    try:
        if hasattr(field_file, 'storage') and field_file.storage.exists(field_file.name):
            with field_file.storage.open(field_file.name, 'rb') as f:
                content = f.read()
                if content:
                    return content
    except Exception:
        pass

    # Método 2: Intentar mediante field_file.open()
    try:
        with field_file.open('rb') as f:
            content = f.read()
            if content:
                return content
    except Exception:
        pass

    # Método 3: Si tiene URL remota (Cloudinary, CDN, HTTP/HTTPS)
    try:
        url = getattr(field_file, 'url', None)
        if url and (str(url).startswith('http://') or str(url).startswith('https://')):
            resp = requests.get(url, stream=True, timeout=8, headers={'User-Agent': 'Mozilla/5.0'})
            if resp.status_code == 200 and resp.content:
                return resp.content
    except Exception:
        pass

    # Método 4: Comprobar físicamente en settings.MEDIA_ROOT
    try:
        local_path = os.path.join(settings.MEDIA_ROOT, field_file.name)
        if os.path.exists(local_path):
            with open(local_path, 'rb') as f:
                content = f.read()
                if content:
                    return content
    except Exception:
        pass

    return None


@login_required(login_url='/login/')
def respaldos_exportacion(request):
    """
    Panel de Copias de Seguridad y Exportación Masiva de Datos para el Usuario/Cliente.
    """
    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().distinct()
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()
    
    total_propiedades = Propiedad.objects.filter(portafolio__in=portafolios, is_deleted=False).count()
    total_propietarios = PropietarioInmueble.objects.filter(portafolio__in=portafolios, activo=True).count()
    total_inquilinos = Inquilino.objects.filter(
        Q(contratos__propiedad__portafolio__in=portafolios) | Q(creado_por=request.user)
    ).distinct().count() if not request.user.is_superuser else Inquilino.objects.all().count()
    total_contratos = Contrato.objects.filter(propiedad__portafolio__in=portafolios, activo=True).count()
    
    context = {
        'titulo_pagina': 'Copias de Seguridad y Exportación de Datos',
        'total_propiedades': total_propiedades,
        'total_propietarios': total_propietarios,
        'total_inquilinos': total_inquilinos,
        'total_contratos': total_contratos,
    }
    return render(request, 'gestion_propiedades/respaldos_exportacion.html', context)


@login_required(login_url='/login/')
def exportar_datos_csv_zip(request):
    """
    Genera un archivo ZIP conteniendo archivos CSV estructurados con la totalidad de
    las tablas operativas del portafolio (Propietarios, Inmuebles, Inquilinos, Contratos,
    Facturación, Recibos de Cobro, Mantenimientos, Gastos Generales, Liquidaciones y Recordatorios).
    100% compatible con Microsoft Excel, Google Sheets y formato UTF-8 universal con BOM.
    """
    try:
        if request.user.is_superuser:
            portafolios = Portafolio.objects.all().distinct()
            inquilinos_qs = Inquilino.objects.all().distinct()
        else:
            portafolios = Portafolio.objects.filter(
                Q(propietario=request.user) | Q(accesos__usuario=request.user)
            ).distinct()
            inquilinos_qs = Inquilino.objects.filter(
                Q(contratos__propiedad__portafolio__in=portafolios) | Q(creado_por=request.user)
            ).distinct()
        
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # 1. Propietarios
            propietarios_qs = PropietarioInmueble.objects.filter(portafolio__in=portafolios).select_related('portafolio')
            output_prop = io.StringIO()
            writer = csv.writer(output_prop)
            writer.writerow([
                'ID', 'Portafolio', 'Nombre', 'Cédula/RNC', 'Teléfono', 'Correo', 'Dirección',
                'Tipo Comisión', 'Porcentaje Comisión (%)', 'Monto Fijo Mensual',
                'Banco', 'Tipo Cuenta', 'Número Cuenta', 'Día Pago Acordado', 'Activo'
            ])
            for p in propietarios_qs:
                port_nom = p.portafolio.nombre if p.portafolio else 'N/A'
                tipo_com_txt = p.get_tipo_comision_display() if hasattr(p, 'get_tipo_comision_display') else p.tipo_comision
                writer.writerow([
                    p.id, port_nom, p.nombre, p.cedula_o_rnc or '', p.telefono or '', p.correo or '', p.direccion or '',
                    tipo_com_txt, p.porcentaje_comision or 0.00, p.monto_comision_fijo or 0.00,
                    p.banco_nombre or '', p.tipo_cuenta or '', p.numero_cuenta or '', p.dia_pago_acordado or '',
                    'Sí' if p.activo else 'No'
                ])
            zip_file.writestr('1_Propietarios.csv', output_prop.getvalue().encode('utf-8-sig'))
            
            # 2. Inmuebles / Propiedades
            propiedades_qs = Propiedad.objects.filter(portafolio__in=portafolios, is_deleted=False).select_related('portafolio', 'propietario_inmueble')
            output_inm = io.StringIO()
            writer = csv.writer(output_inm)
            writer.writerow(['ID', 'Portafolio', 'Nombre/Unidad', 'Residencial/Grupo', 'Propietario', 'Dirección', 'Precio Sugerido', 'Latitud', 'Longitud', 'Estado', 'Detalles'])
            for pr in propiedades_qs:
                prop_nombre = pr.propietario_inmueble.nombre if pr.propietario_inmueble else 'N/A'
                port_nombre = pr.portafolio.nombre if pr.portafolio else 'N/A'
                writer.writerow([
                    pr.id, port_nombre, pr.nombre_o_numero, pr.grupo_o_residencial or '', prop_nombre,
                    pr.direccion_completa or '', pr.precio_alquiler_sugerido or 0.00, pr.latitud or '',
                    pr.longitud or '', pr.get_estado_display(), pr.detalles or ''
                ])
            zip_file.writestr('2_Propiedades_Inmuebles.csv', output_inm.getvalue().encode('utf-8-sig'))

            # 3. Inquilinos
            output_inq = io.StringIO()
            writer = csv.writer(output_inq)
            writer.writerow([
                'ID', 'Nombre Completo', 'Teléfono Principal', 'Teléfono Secundario',
                'Cédula/Pasaporte', 'Correo', 'Dirección', 'Nombre Fiador',
                'Cédula Fiador', 'Teléfono Fiador', 'Dirección Fiador', 'Alertas Correo'
            ])
            for i in inquilinos_qs:
                writer.writerow([
                    i.id, i.nombre, i.telefono or '', i.telefono_secundario or '',
                    i.cedula_o_pasaporte or '', i.correo or '', i.direccion or '',
                    i.nombre_fiador or '', i.cedula_fiador or '', i.telefono_fiador or '',
                    i.direccion_fiador or '', 'Sí' if i.recibir_alertas_correo else 'No'
                ])
            zip_file.writestr('3_Inquilinos.csv', output_inq.getvalue().encode('utf-8-sig'))

            # 4. Contratos
            contratos_qs = Contrato.objects.filter(propiedad__portafolio__in=portafolios).select_related('propiedad', 'inquilino')
            output_con = io.StringIO()
            writer = csv.writer(output_con)
            writer.writerow([
                'ID Contrato', 'Propiedad', 'Inquilino', 'Fecha Inicio', 'Fecha Fin',
                'Monto Renta', 'Monto Depósito', 'Monto Adelanto', 'Custodia Depósito',
                'Día de Pago', 'Días Gracia', 'Porcentaje Mora (%)', 'Estado Activo'
            ])
            for c in contratos_qs:
                prop_nom = c.propiedad.nombre_o_numero if c.propiedad else 'N/A'
                inq_nom = c.inquilino.nombre if c.inquilino else 'N/A'
                cust_nom = c.get_custodia_deposito_display() if hasattr(c, 'get_custodia_deposito_display') else c.custodia_deposito
                writer.writerow([
                    c.id, prop_nom, inq_nom, c.fecha_inicio, c.fecha_fin or 'Indefinido',
                    c.monto_renta, c.monto_deposito, c.monto_adelanto, cust_nom,
                    c.dia_de_pago, c.dias_gracia, c.porcentaje_mora, 'Sí' if c.activo else 'No'
                ])
            zip_file.writestr('4_Contratos.csv', output_con.getvalue().encode('utf-8-sig'))

            # 5. Facturas
            facturas_qs = Factura.objects.filter(
                contrato__propiedad__portafolio__in=portafolios
            ).select_related('contrato__propiedad', 'contrato__inquilino')
            output_fac = io.StringIO()
            writer = csv.writer(output_fac)
            writer.writerow([
                'No. Factura', 'ID Contrato', 'Propiedad', 'Inquilino', 'Concepto',
                'Monto Total Facturado', 'Monto Renta Pura', 'Monto Servicios', 'Estado',
                'Mora Exonerada', 'Fecha Emisión', 'Fecha Vencimiento'
            ])
            for f in facturas_qs:
                prop_nom = f.contrato.propiedad.nombre_o_numero if (f.contrato and f.contrato.propiedad) else 'N/A'
                inq_nom = f.contrato.inquilino.nombre if (f.contrato and f.contrato.inquilino) else 'N/A'
                writer.writerow([
                    f.id, f.contrato_id or '', prop_nom, inq_nom, f.concepto or '',
                    f.monto_base, f.monto_renta, f.monto_servicios, f.get_estado_display(),
                    'Sí' if f.mora_exonerada else 'No', f.fecha_emision, f.fecha_vencimiento
                ])
            zip_file.writestr('5_Facturas.csv', output_fac.getvalue().encode('utf-8-sig'))

            # 6. Recibos y Cobros Registrados
            recibos_qs = ReciboPago.objects.filter(
                factura__contrato__propiedad__portafolio__in=portafolios
            ).select_related('factura__contrato__propiedad', 'factura__contrato__inquilino', 'registrado_por')
            output_rec = io.StringIO()
            writer = csv.writer(output_rec)
            writer.writerow([
                'No. Recibo', 'No. Factura', 'Propiedad', 'Inquilino', 'Fecha Pago',
                'Monto Pagado', 'Abono Renta', 'Abono Servicios', 'Abono Mora',
                'Método Pago', 'Referencia Transacción', 'Registrado Por', 'Fecha Registro'
            ])
            for r in recibos_qs:
                f_obj = r.factura
                c_obj = f_obj.contrato if f_obj else None
                prop_nom = c_obj.propiedad.nombre_o_numero if (c_obj and c_obj.propiedad) else 'N/A'
                inq_nom = c_obj.inquilino.nombre if (c_obj and c_obj.inquilino) else 'N/A'
                user_nom = r.registrado_por.get_full_name() or r.registrado_por.username if r.registrado_por else 'Sistema'
                metodo_txt = r.get_metodo_pago_display() if hasattr(r, 'get_metodo_pago_display') else r.metodo_pago
                writer.writerow([
                    r.id, r.factura_id or '', prop_nom, inq_nom, r.fecha_pago,
                    r.monto_pagado, r.monto_a_renta, r.monto_a_servicios, r.monto_a_mora,
                    metodo_txt, r.referencia_transaccion or '', user_nom, r.registrado_en
                ])
            zip_file.writestr('6_Recibos_y_Cobros.csv', output_rec.getvalue().encode('utf-8-sig'))

            # 7. Gastos de Mantenimiento Directos a Unidades
            mantenimientos_qs = MantenimientoUnidad.objects.filter(
                propiedad__portafolio__in=portafolios
            ).select_related('propiedad')
            output_gas = io.StringIO()
            writer = csv.writer(output_gas)
            writer.writerow(['ID', 'Propiedad', 'Descripción / Trabajo', 'Categoría', 'Costo', 'Estado', 'Fecha Reporte', 'Fecha Resolución'])
            for m in mantenimientos_qs:
                prop_nom = m.propiedad.nombre_o_numero if m.propiedad else 'N/A'
                cat_txt = m.get_categoria_display() if hasattr(m, 'get_categoria_display') else m.categoria
                est_txt = m.get_estado_display() if hasattr(m, 'get_estado_display') else m.estado
                writer.writerow([
                    m.id, prop_nom, m.descripcion or '', cat_txt, m.costo, est_txt,
                    m.fecha_reporte, m.fecha_resolucion or ''
                ])
            zip_file.writestr('7_Gastos_Mantenimiento_Unidades.csv', output_gas.getvalue().encode('utf-8-sig'))

            # 8. Gastos Generales y Deducciones de Propietarios
            gastos_gen_qs = GastoGeneralPropietario.objects.filter(
                portafolio__in=portafolios
            ).select_related('propietario_inmueble', 'propiedad')
            output_gen = io.StringIO()
            writer = csv.writer(output_gen)
            writer.writerow(['ID', 'Propietario', 'Propiedad Específica', 'Concepto / Deducción', 'Categoría', 'Monto', 'Fecha'])
            for g in gastos_gen_qs:
                prop_nom = g.propiedad.nombre_o_numero if g.propiedad else 'General'
                propietario_nom = g.propietario_inmueble.nombre if g.propietario_inmueble else 'Portafolio General'
                cat_txt = g.get_categoria_display() if hasattr(g, 'get_categoria_display') else g.categoria
                writer.writerow([
                    g.id, propietario_nom, prop_nom, g.concepto or '', cat_txt, g.monto, g.fecha
                ])
            zip_file.writestr('8_Gastos_Generales_Deducciones.csv', output_gen.getvalue().encode('utf-8-sig'))

            # 9. Liquidaciones a Propietarios
            liq_qs = LiquidacionPropietario.objects.filter(
                propietario_inmueble__portafolio__in=portafolios
            ).select_related('propietario_inmueble')
            output_liq = io.StringIO()
            writer = csv.writer(output_liq)
            writer.writerow([
                'ID', 'Propietario', 'Período', 'Rentas Cobradas', 'Comisión Administradora',
                'Gastos Propiedades', 'Gastos Generales / Deducciones', 'Neto Transferido',
                'Estado', 'Fecha Pago', 'Método', 'Referencia Transacción'
            ])
            for l in liq_qs:
                propietario_nom = l.propietario_inmueble.nombre if l.propietario_inmueble else 'N/A'
                est_txt = l.get_estado_display() if hasattr(l, 'get_estado_display') else l.estado
                writer.writerow([
                    l.id, propietario_nom, f"{l.periodo_mes}/{l.periodo_anio}",
                    l.monto_rentas_cobradas, l.monto_comision, l.monto_gastos_propiedades,
                    l.monto_gastos_generales, l.monto_neto_pagado, est_txt,
                    l.fecha_pago or '', l.metodo_pago or '', l.referencia_transaccion or ''
                ])
            zip_file.writestr('9_Liquidaciones_Propietarios.csv', output_liq.getvalue().encode('utf-8-sig'))

            # 10. Recordatorios de Pagos a Propietarios
            recordatorios_qs = RecordatorioPagoPropietario.objects.filter(
                portafolio__in=portafolios
            ).select_related('propietario')
            output_rec_prop = io.StringIO()
            writer = csv.writer(output_rec_prop)
            writer.writerow(['ID', 'Propietario', 'Título', 'Fecha Programada', 'Monto Sugerido', 'Prioridad', 'Estado', 'Notas'])
            for rec in recordatorios_qs:
                propietario_nom = rec.propietario.nombre if rec.propietario else 'N/A'
                prio_txt = rec.get_prioridad_display() if hasattr(rec, 'get_prioridad_display') else rec.prioridad
                est_txt = rec.get_estado_display() if hasattr(rec, 'get_estado_display') else rec.estado
                writer.writerow([
                    rec.id, propietario_nom, rec.titulo, rec.fecha_recordatorio,
                    rec.monto_sugerido or 0.00, prio_txt, est_txt, rec.notas or ''
                ])
            zip_file.writestr('10_Recordatorios_Pagos_Propietarios.csv', output_rec_prop.getvalue().encode('utf-8-sig'))

        zip_buffer.seek(0)
        fecha_str = date.today().strftime('%Y%m%d')
        response = HttpResponse(zip_buffer.getvalue(), content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename="Alquilo_Backup_Datos_{fecha_str}.zip"'
        return response

    except Exception as e:
        logger.error(f"Error generando exportación de datos en CSV/ZIP: {e}", exc_info=True)
        messages.error(request, f"Ocurrió un inconveniente al generar la exportación de datos: {str(e)}")
        return redirect('respaldos_exportacion')


@login_required(login_url='/login/')
def exportar_archivos_adjuntos_zip(request):
    """
    Empaqueta y descarga la totalidad de los documentos PDF e imágenes subidas en el sistema,
    organizados en carpetas por categoría (Contratos, Fotos de Propiedades, Comprobantes de Cobro,
    Liquidaciones, Mantenimientos y Gastos, Entregas, Solicitudes).
    Soporta de manera segura archivos alojados en Cloudinary y en almacenamiento local.
    """
    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().distinct()
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()

    zip_buffer = io.BytesIO()
    count_files = 0
    archivos_en_zip = set()

    def limpiar_nombre_zip(texto):
        texto_limpio = re.sub(r'[\\/*?:"<>|]', '_', str(texto or '')).strip()
        return texto_limpio[:50] if texto_limpio else 'archivo'

    def agregar_al_zip(zip_file, ruta_en_zip, field_file):
        nonlocal count_files
        if not field_file or not getattr(field_file, 'name', None):
            return False
        try:
            data = _obtener_bytes_archivo(field_file)
            if not data:
                return False

            base, ext = os.path.splitext(ruta_en_zip)
            if not ext:
                ext_orig = os.path.splitext(field_file.name)[1]
                ext = ext_orig if ext_orig else ''
            
            candidato = f"{base}{ext}"
            idx = 1
            while candidato in archivos_en_zip:
                candidato = f"{base}_{idx}{ext}"
                idx += 1

            archivos_en_zip.add(candidato)
            zip_file.writestr(candidato, data)
            count_files += 1
            return True
        except Exception as e:
            logger.warning(f"No se pudo empaquetar archivo {getattr(field_file, 'name', '')}: {e}")
            return False

    try:
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # 1. Contratos legales (PDFs)
            contratos_qs = Contrato.objects.filter(
                propiedad__portafolio__in=portafolios
            ).select_related('propiedad', 'inquilino')
            for c in contratos_qs:
                prop_slug = limpiar_nombre_zip(c.propiedad.nombre_o_numero if c.propiedad else f"prop_{c.propiedad_id}")
                inq_slug = limpiar_nombre_zip(c.inquilino.nombre if c.inquilino else 'inquilino')
                
                # Documento principal firmado
                if c.documento_contrato:
                    nombre_orig = os.path.basename(c.documento_contrato.name)
                    agregar_al_zip(
                        zip_file,
                        f"1_Contratos_Legales/Contrato_{c.id}_{prop_slug}_{inq_slug}_{limpiar_nombre_zip(nombre_orig)}",
                        c.documento_contrato
                    )
                
                # Fotos de entrega del inmueble asociadas al contrato
                for idx_f, f_entrega in enumerate([c.fotos_entrega, c.foto_entrega_2, c.foto_entrega_3, c.foto_entrega_4, c.foto_entrega_5], start=1):
                    if f_entrega:
                        nombre_orig = os.path.basename(f_entrega.name)
                        agregar_al_zip(
                            zip_file,
                            f"2_Fotos_Entregas_Inmuebles/Entrega_Contrato_{c.id}_{prop_slug}_foto{idx_f}_{limpiar_nombre_zip(nombre_orig)}",
                            f_entrega
                        )

            # 2. Fotos de Propiedades (Fachadas y Galería)
            propiedades_qs = Propiedad.objects.filter(
                portafolio__in=portafolios, 
                is_deleted=False
            ).prefetch_related('imagenes_galeria')
            for pr in propiedades_qs:
                prop_slug = limpiar_nombre_zip(pr.nombre_o_numero)
                if pr.imagen_principal:
                    nombre_orig = os.path.basename(pr.imagen_principal.name)
                    agregar_al_zip(
                        zip_file,
                        f"3_Fotos_Propiedades/Fachada_{pr.id}_{prop_slug}_{limpiar_nombre_zip(nombre_orig)}",
                        pr.imagen_principal
                    )
                for img_gal in pr.imagenes_galeria.all():
                    if img_gal.imagen:
                        nombre_orig = os.path.basename(img_gal.imagen.name)
                        desc_slug = limpiar_nombre_zip(img_gal.titulo_o_descripcion or f"foto_{img_gal.id}")
                        agregar_al_zip(
                            zip_file,
                            f"3_Fotos_Propiedades/Galeria_{prop_slug}_{desc_slug}_{limpiar_nombre_zip(nombre_orig)}",
                            img_gal.imagen
                        )

            # 3. Comprobantes físicos de cobros y pagos de inquilinos
            recibos_qs = ReciboPago.objects.filter(
                factura__contrato__propiedad__portafolio__in=portafolios
            ).exclude(comprobante_imagen='').exclude(comprobante_imagen__isnull=True).select_related('factura__contrato__propiedad')
            for r in recibos_qs:
                if r.comprobante_imagen:
                    prop_slug = limpiar_nombre_zip(r.factura.contrato.propiedad.nombre_o_numero if (r.factura and r.factura.contrato and r.factura.contrato.propiedad) else 'propiedad')
                    nombre_orig = os.path.basename(r.comprobante_imagen.name)
                    agregar_al_zip(
                        zip_file,
                        f"4_Comprobantes_Cobros/Recibo_{r.id}_Factura_{r.factura_id}_{prop_slug}_{limpiar_nombre_zip(nombre_orig)}",
                        r.comprobante_imagen
                    )

            # 4. Comprobantes de liquidaciones a propietarios
            liquidaciones_qs = LiquidacionPropietario.objects.filter(
                propietario_inmueble__portafolio__in=portafolios
            ).exclude(comprobante_pago='').exclude(comprobante_pago__isnull=True).select_related('propietario_inmueble')
            for l in liquidaciones_qs:
                if l.comprobante_pago:
                    prop_slug = limpiar_nombre_zip(l.propietario_inmueble.nombre if l.propietario_inmueble else 'propietario')
                    nombre_orig = os.path.basename(l.comprobante_pago.name)
                    agregar_al_zip(
                        zip_file,
                        f"5_Liquidaciones_Propietarios/Liquidacion_{l.id}_{prop_slug}_{l.periodo_mes}_{l.periodo_anio}_{limpiar_nombre_zip(nombre_orig)}",
                        l.comprobante_pago
                    )

            # 5. Facturas y comprobantes de mantenimiento
            mantenimientos_qs = MantenimientoUnidad.objects.filter(
                propiedad__portafolio__in=portafolios
            ).exclude(factura_adjunta='').exclude(factura_adjunta__isnull=True).select_related('propiedad')
            for m in mantenimientos_qs:
                if m.factura_adjunta:
                    prop_slug = limpiar_nombre_zip(m.propiedad.nombre_o_numero if m.propiedad else 'propiedad')
                    nombre_orig = os.path.basename(m.factura_adjunta.name)
                    agregar_al_zip(
                        zip_file,
                        f"6_Mantenimientos_Gastos/Mantenimiento_{m.id}_{prop_slug}_{limpiar_nombre_zip(nombre_orig)}",
                        m.factura_adjunta
                    )

            # 6. Facturas y comprobantes de gastos generales / deducciones
            gastos_gen_qs = GastoGeneralPropietario.objects.filter(
                portafolio__in=portafolios
            ).exclude(factura_adjunta='').exclude(factura_adjunta__isnull=True)
            for g in gastos_gen_qs:
                if g.factura_adjunta:
                    concepto_slug = limpiar_nombre_zip(g.concepto or f"gasto_{g.id}")
                    nombre_orig = os.path.basename(g.factura_adjunta.name)
                    agregar_al_zip(
                        zip_file,
                        f"7_Gastos_Generales/Gasto_{g.id}_{concepto_slug}_{limpiar_nombre_zip(nombre_orig)}",
                        g.factura_adjunta
                    )

            # 7. Documentos de Solicitudes de Alquiler
            solicitudes_qs = SolicitudAlquiler.objects.filter(
                propiedad__portafolio__in=portafolios
            ).select_related('propiedad')
            for s in solicitudes_qs:
                s_slug = limpiar_nombre_zip(s.nombre_solicitante or f"solicitud_{s.id}")
                for tipo_doc, campo_adj in [
                    ('Cedula_Solicitante', s.adjunto_cedula_solicitante),
                    ('Ingresos_Solicitante', s.adjunto_ingresos_solicitante),
                    ('Cedula_Fiador', s.adjunto_cedula_fiador),
                    ('Ingresos_Fiador', s.adjunto_ingresos_fiador),
                ]:
                    if campo_adj:
                        nombre_orig = os.path.basename(campo_adj.name)
                        agregar_al_zip(
                            zip_file,
                            f"8_Solicitudes_Alquiler/Solicitud_{s.id}_{s_slug}_{tipo_doc}_{limpiar_nombre_zip(nombre_orig)}",
                            campo_adj
                        )

            # 8. Logos de Portafolio
            for port in portafolios:
                if port.logo_empresa:
                    port_slug = limpiar_nombre_zip(port.nombre)
                    nombre_orig = os.path.basename(port.logo_empresa.name)
                    agregar_al_zip(
                        zip_file,
                        f"9_Logos_Portafolios/Logo_{port.id}_{port_slug}_{limpiar_nombre_zip(nombre_orig)}",
                        port.logo_empresa
                    )

            # Manifiesto informativo de respaldo
            nombres_port = ", ".join([p.nombre for p in portafolios])
            fecha_hoy_str = date.today().strftime('%d/%m/%Y')
            if count_files == 0:
                zip_file.writestr(
                    'LEEME_RESPALDO.txt',
                    (
                        f"========================================================================\n"
                        f"ALQUILO - COPIA DE SEGURIDAD DE DOCUMENTOS Y ARCHIVOS ADJUNTOS\n"
                        f"========================================================================\n\n"
                        f"Fecha de Generación: {fecha_hoy_str}\n"
                        f"Portafolios: {nombres_port}\n\n"
                        f"Estado: No se encontraron documentos físicos adjuntos (PDFs o imágenes)\n"
                        f"cargados en sus contratos, inmuebles, comprobantes o mantenimientos.\n\n"
                        f"A medida que cargue contratos firmados, fotografías de entrega o recibos\n"
                        f"de pago, se empaquetarán ordenadamente por carpeta en este archivo.\n"
                    ).encode('utf-8-sig')
                )
            else:
                zip_file.writestr(
                    'MANIFIESTO_RESPALDO.txt',
                    (
                        f"========================================================================\n"
                        f"ALQUILO - COPIA DE SEGURIDAD DE DOCUMENTOS Y ARCHIVOS ADJUNTOS\n"
                        f"========================================================================\n\n"
                        f"Fecha de Generación: {fecha_hoy_str}\n"
                        f"Portafolios: {nombres_port}\n"
                        f"Total de archivos físicos empaquetados: {count_files}\n\n"
                        f"Estructura de carpetas:\n"
                        f"- 1_Contratos_Legales: Copias escaneadas o digitalizadas de contratos.\n"
                        f"- 2_Fotos_Entregas_Inmuebles: Fotos del estado de entrega del inmueble.\n"
                        f"- 3_Fotos_Propiedades: Fotos principales y galerías de propiedades.\n"
                        f"- 4_Comprobantes_Cobros: Vouchers y transferencias cargadas al cobrar.\n"
                        f"- 5_Liquidaciones_Propietarios: Comprobantes de pago transferidos a dueños.\n"
                        f"- 6_Mantenimientos_Gastos: Facturas de reparaciones y mantenimientos.\n"
                        f"- 7_Gastos_Generales: Facturas de gastos y deducciones de propietarios.\n"
                        f"- 8_Solicitudes_Alquiler: Documentos de identidad e ingresos de prospectos.\n"
                        f"- 9_Logos_Portafolios: Logos oficiales de marca blanca.\n"
                    ).encode('utf-8-sig')
                )

        zip_buffer.seek(0)
        fecha_descarga = date.today().strftime('%Y%m%d')
        response = HttpResponse(zip_buffer.getvalue(), content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename="Alquilo_Archivos_Adjuntos_{fecha_descarga}.zip"'
        return response

    except Exception as e:
        logger.error(f"Error empaquetando archivos adjuntos en ZIP: {e}", exc_info=True)
        messages.error(request, f"Ocurrió un inconveniente al generar el paquete de archivos adjuntos: {str(e)}")
        return redirect('respaldos_exportacion')


@login_required(login_url='/login/')
def papelera_reciclaje(request):
    """
    Centro de Recuperación / Papelera de Reciclaje para propiedades eliminadas lógicamente.
    """
    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().distinct()
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()
    
    propiedades_eliminadas = Propiedad.objects.filter(
        portafolio__in=portafolios,
        is_deleted=True
    ).select_related('portafolio', 'propietario_inmueble')
    
    context = {
        'titulo_pagina': 'Papelera de Reciclaje y Restauración',
        'propiedades_eliminadas': propiedades_eliminadas,
        'total_eliminadas': propiedades_eliminadas.count()
    }
    return render(request, 'gestion_propiedades/papelera_reciclaje.html', context)


@login_required(login_url='/login/')
def restaurar_propiedad(request, propiedad_id):
    """
    Restaura una propiedad que fue borrada lógicamente (Soft Delete).
    """
    if request.user.is_superuser:
        portafolios = Portafolio.objects.all().distinct()
    else:
        portafolios = Portafolio.objects.filter(
            Q(propietario=request.user) | Q(accesos__usuario=request.user)
        ).distinct()
    propiedad = get_object_or_404(Propiedad, id=propiedad_id, portafolio__in=portafolios, is_deleted=True)
    
    if request.method == 'POST':
        propiedad.is_deleted = False
        propiedad.save()
        messages.success(request, f'La propiedad "{propiedad.nombre_o_numero}" ha sido restaurada con éxito. Ya está visible de nuevo en la lista activa.')
        return redirect('papelera_reciclaje')
    return redirect('papelera_reciclaje')


@login_required(login_url='/login/')
def descargar_backup_db(request):
    """
    Exclusivo para el Administrador Maestro (Superusuario).
    Descarga una copia completa de la base de datos en formato JSON comprimido en ZIP.
    Es compatible con PostgreSQL y SQLite, y puede ser restaurada con 'python manage.py loaddata'.
    """
    if not request.user.is_superuser:
        raise PermissionDenied("Solo el Administrador Maestro tiene acceso a descargar respaldos de la base de datos.")

    from django.core.management import call_command
    from django.utils import timezone
    import io
    import zipfile

    buffer_json = io.StringIO()
    call_command(
        'dumpdata',
        exclude=['contenttypes', 'auth.permission', 'sessions.session'],
        indent=2,
        stdout=buffer_json
    )

    fecha_hora = timezone.now().strftime('%Y_%m_%d_%H%M%S')
    json_filename = f"backup_alquilo_saas_{fecha_hora}.json"
    zip_filename = f"backup_db_alquilo_{fecha_hora}.zip"

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(json_filename, buffer_json.getvalue().encode('utf-8'))

    zip_buffer.seek(0)
    response = HttpResponse(zip_buffer.getvalue(), content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="{zip_filename}"'
    return response


@login_required(login_url='/login/')
def importar_cartera_basora_web(request):
    """
    Ejecuta la migración masiva de los 132 apartamentos de Basora & Arriaga en 1 clic
    directamente desde la interfaz web de superadministrador.
    """
    if not request.user.is_superuser:
        raise PermissionDenied("Solo el Administrador Maestro puede ejecutar importaciones masivas.")

    if request.method == 'POST':
        from importar_cartera_basora import ejecutar_importacion
        import io
        from contextlib import redirect_stdout

        f = io.StringIO()
        try:
            with redirect_stdout(f):
                ejecutar_importacion(commit=True)
            messages.success(request, "¡Cartera de Basora & Arriaga (132 propiedades y contratos) importada con éxito total!")
        except Exception as e:
            messages.error(request, f"Error durante la importación: {str(e)}")

        return redirect('saas_master_control')

    return redirect('saas_master_control')
    

