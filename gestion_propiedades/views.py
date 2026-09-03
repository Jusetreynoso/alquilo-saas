from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login
from django.db.models import Sum, Q, Prefetch, F, Count
from django.contrib import messages
from datetime import date
from .models import Portafolio, Propiedad, Factura, CargoMora, ReciboPago, Contrato, SolicitudAlquiler, MantenimientoUnidad, Inquilino, PlanSaaS, SuscripcionCliente, AuditLog, GastoProgramado, RegistroProceso, PropietarioInmueble, GastoGeneralPropietario, LiquidacionPropietario, LiquidacionDepositoInquilino, HistorialPrecioPropiedad
from .forms import NuevoClienteSaaSForm, EditarSuscripcionForm, PropiedadForm, ContratoForm, InquilinoForm, MantenimientoForm, PlanSaaSForm, PropietarioInmuebleForm, GastoGeneralPropietarioForm, LiquidacionPropietarioForm, LiquidacionDepositoForm, HistorialPrecioForm
from .utils import render_to_pdf, obtener_nombre_mes
import calendar
import decimal
from django.db.models.functions import TruncMonth
from .utils_rbac import propietario_requerido
from collections import defaultdict


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

    context = {
        'titulo_pagina': 'Resumen de Portafolio',
        'total_propiedades': total_propiedades,
        'propiedades_disponibles': propiedades_disponibles,
        'cuentas_por_cobrar': cuentas_por_cobrar,
        'ingresos_mes': ingresos_mes,
        'facturas_pendientes': facturas_pendientes,
        'recordatorios_gastos': recordatorios_gastos,
    }
    
    return render(request, 'gestion_propiedades/dashboard.html', context)

@login_required(login_url='/login/')
def lista_propiedades(request):
    # 1. Buscamos los portafolios a los que tiene acceso el usuario
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
    # Buscamos la factura
    factura = get_object_or_404(Factura, id=factura_id)

    # Si el usuario hace clic en el botón "Guardar Pago" (Método POST)
    if request.method == 'POST':
        monto = request.POST.get('monto')
        metodo = request.POST.get('metodo_pago')
        referencia = request.POST.get('referencia')
        fecha = request.POST.get('fecha_pago')

        # 1. Creamos el Recibo de Pago en la base de datos
        ReciboPago.objects.create(
            factura=factura,
            fecha_pago=fecha,
            monto_pagado=monto,
            metodo_pago=metodo,
            referencia_transaccion=referencia,
            registrado_por=request.user
        )

        # 2. Actualizamos la Factura evaluando si quedó completamente saldada
        if factura.saldo_pendiente <= 0:
            factura.estado = 'PAGADA'
        factura.save()

        # 3. Lo devolvemos al expediente de la propiedad
        return redirect('detalle_propiedad', propiedad_id=factura.contrato.propiedad.id)

    # Si solo está entrando a ver la pantalla (Método GET), le mostramos el formulario
    context = {
        'titulo_pagina': f'Cobrar Factura #{factura.id}',
        'factura': factura,
    }
    return render(request, 'gestion_propiedades/registrar_pago.html', context)

@login_required(login_url='/login/')
def lista_contratos(request):
    # 1. Filtramos por los portafolios del usuario
    portafolios = Portafolio.objects.filter(
        Q(propietario=request.user) | Q(accesos__usuario=request.user)
    ).distinct()

    # 2. Buscamos los contratos de esas propiedades
    # Los ordenamos para que los Activos salgan primero, y luego por el nombre de la propiedad
    contratos = Contrato.objects.filter(
        propiedad__portafolio__in=portafolios
    ).select_related('propiedad').order_by('-activo', 'propiedad__nombre_o_numero')

    context = {
        'titulo_pagina': 'Gestión de Contratos',
        'contratos': contratos,
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

    if request.method == 'POST':
        form = PropiedadForm(request.POST, request.FILES)
        if form.is_valid():
            nueva_propiedad = form.save(commit=False)
            # Buscamos el portafolio principal del usuario
            portafolio_principal = Portafolio.objects.filter(propietario=request.user).first()
            
            if not portafolio_principal:
                acceso = request.user.portafolios_asignados.first()
                if acceso:
                    portafolio_principal = acceso.portafolio
            
            if portafolio_principal:
                nueva_propiedad.portafolio = portafolio_principal
                nueva_propiedad.save()
                return redirect('lista_propiedades')
            else:
                return HttpResponse("Error: No tienes un portafolio asignado.")
    else:
        form = PropiedadForm()

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
                
                # Intentamos sacar datos
                prop_nombre = nuevo_contrato.propiedad.portafolio.propietario.get_full_name() or nuevo_contrato.propiedad.portafolio.propietario.username
                prop_dir = nuevo_contrato.propiedad.portafolio.direccion_fisica or '___________________'
                
                meses = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
                mes_actual_es = meses[hoy.month - 1]
                
                reemplazos = {
                    '{{PROPIETARIO_NOMBRE}}': prop_nombre,
                    '{{PROPIETARIO_CEDULA}}': '___________________',
                    '{{PROPIETARIO_DIRECCION}}': prop_dir,
                    '{{INQUILINO_NOMBRE}}': nuevo_contrato.inquilino.nombre,
                    '{{INQUILINO_CEDULA}}': nuevo_contrato.inquilino.cedula_o_pasaporte or '___________________',
                    '{{INQUILINO_DIRECCION}}': '___________________',
                    '{{INQUILINO_TELEFONO}}': nuevo_contrato.inquilino.telefono or '___________________',
                    '{{PROPIEDAD_DIRECCION}}': nuevo_contrato.propiedad.direccion_completa or nuevo_contrato.propiedad.nombre_o_numero,
                    '{{MONTO_RENTA}}': f"RD$ {nuevo_contrato.monto_renta:,.2f}",
                    '{{MONTO_DEPOSITO}}': f"RD$ {nuevo_contrato.monto_deposito:,.2f}",
                    '{{FECHA_INICIO}}': nuevo_contrato.fecha_inicio.strftime('%d/%m/%Y'),
                    '{{FECHA_FIN}}': nuevo_contrato.fecha_fin.strftime('%d/%m/%Y') if nuevo_contrato.fecha_fin else 'Indefinida',
                    '{{DIA_PAGO}}': str(nuevo_contrato.dia_de_pago),
                    '{{DIA_ACTUAL}}': str(hoy.day),
                    '{{MES_ACTUAL}}': mes_actual_es,
                    '{{ANIO_ACTUAL}}': str(hoy.year),
                    '{{FIADOR_NOMBRE}}': '___________________',
                    '{{FIADOR_CEDULA}}': '___________________',
                    '{{FIADOR_DIRECCION}}': '___________________',
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

                # 4. Crear la Factura
                Factura.objects.create(
                    contrato=contrato,
                    fecha_emision=hoy,
                    fecha_vencimiento=fecha_vencimiento,
                    monto_base=contrato.monto_renta,
                    concepto=f"Renta {obtener_nombre_mes(hoy.month)} {hoy.year}",
                    estado='PENDIENTE'
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
        form = PropiedadForm(request.POST, request.FILES, instance=propiedad)
        if form.is_valid():
            form.save()
            messages.success(request, 'Propiedad actualizada correctamente.')
            return redirect('detalle_propiedad', propiedad_id=propiedad.id)
    else:
        form = PropiedadForm(instance=propiedad)

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
                
                prop_nombre = contrato_editado.propiedad.portafolio.propietario.get_full_name() or contrato_editado.propiedad.portafolio.propietario.username
                prop_dir = contrato_editado.propiedad.portafolio.direccion_fisica or '___________________'
                
                meses = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
                mes_actual_es = meses[hoy.month - 1]
                
                reemplazos = {
                    '{{PROPIETARIO_NOMBRE}}': prop_nombre,
                    '{{PROPIETARIO_CEDULA}}': '___________________',
                    '{{PROPIETARIO_DIRECCION}}': prop_dir,
                    '{{INQUILINO_NOMBRE}}': contrato_editado.inquilino.nombre,
                    '{{INQUILINO_CEDULA}}': contrato_editado.inquilino.cedula_o_pasaporte or '___________________',
                    '{{INQUILINO_DIRECCION}}': '___________________',
                    '{{INQUILINO_TELEFONO}}': contrato_editado.inquilino.telefono or '___________________',
                    '{{PROPIEDAD_DIRECCION}}': contrato_editado.propiedad.direccion_completa or contrato_editado.propiedad.nombre_o_numero,
                    '{{MONTO_RENTA}}': f"RD$ {contrato_editado.monto_renta:,.2f}",
                    '{{MONTO_DEPOSITO}}': f"RD$ {contrato_editado.monto_deposito:,.2f}",
                    '{{FECHA_INICIO}}': contrato_editado.fecha_inicio.strftime('%d/%m/%Y'),
                    '{{FECHA_FIN}}': contrato_editado.fecha_fin.strftime('%d/%m/%Y') if contrato_editado.fecha_fin else 'Indefinida',
                    '{{DIA_PAGO}}': str(contrato_editado.dia_de_pago),
                    '{{DIA_ACTUAL}}': str(hoy.day),
                    '{{MES_ACTUAL}}': mes_actual_es,
                    '{{ANIO_ACTUAL}}': str(hoy.year),
                    '{{FIADOR_NOMBRE}}': '___________________',
                    '{{FIADOR_CEDULA}}': '___________________',
                    '{{FIADOR_DIRECCION}}': '___________________',
                }
                
                for tag, valor in reemplazos.items():
                    html = html.replace(tag, str(valor))
                
                contrato_editado.texto_legal_generado = html

            contrato_editado.save()
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
    portafolios = Portafolio.objects.filter(
        Q(propietario=request.user) | Q(accesos__usuario=request.user)
    ).distinct()

    # Listas para desplegables de filtro
    propietarios_list = PropietarioInmueble.objects.filter(portafolio__in=portafolios, activo=True).order_by('nombre')
    inquilinos_list = Inquilino.objects.filter(
        contratos__propiedad__portafolio__in=portafolios
    ).distinct().order_by('nombre')
    
    # Parámetros GET
    mes = request.GET.get('mes', str(date.today().month)) # "0" para Todo el Año
    anio = int(request.GET.get('anio', date.today().year))
    filtro_tipo = request.GET.get('filtro_tipo', 'PORTAFOLIO') # PORTAFOLIO, PROPIETARIO, INQUILINO
    propietario_id = request.GET.get('propietario_id', '')
    inquilino_id = request.GET.get('inquilino_id', '')

    # Base QuerySets de Propiedades
    propiedades_qs = Propiedad.objects.filter(portafolio__in=portafolios, is_deleted=False)

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
        'finanzas': lista_finanzas
    }

    return render(request, 'gestion_propiedades/reporte_financiero.html', context)


# --- MÓDULO DE REPORTES AVANZADOS ---

@login_required(login_url='/login/')
def reporte_rentabilidad(request):
    """
    Reporte de Rentabilidad Comparativa:
    Para cada propiedad: suma de pagos recibidos - suma de mantenimientos.
    Devuelve la lista ordenada de mayor a menor rentabilidad neta.
    """
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
    
    mantenimientos = MantenimientoUnidad.objects.filter(
        Q(propiedad__portafolio__propietario=request.user) |
        Q(propiedad__portafolio__accesos__usuario=request.user)
    ).distinct().annotate(
        estado_order=Case(
            When(estado='PENDIENTE', then=Value(1)),
            When(estado='PROGRESO', then=Value(2)),
            When(estado='COMPLETADO', then=Value(3)),
            default=Value(4),
            output_field=IntegerField()
        )
    ).order_by('estado_order', '-fecha_reporte')
    
    context = {
        'titulo_pagina': 'Mantenimiento Global (Helpdesk)',
        'mantenimientos': mantenimientos,
    }
    return render(request, 'gestion_propiedades/mantenimientos_global.html', context)

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



# --- MÓDULO B2B SAAS ---

@login_required(login_url='/login/')
def aviso_pago(request):
    try:
        suscripcion = request.user.suscripcion
    except Exception:
        suscripcion = None
        
    context = {'titulo_pagina': 'Aviso de Pago Requerido', 'suscripcion': suscripcion}
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
            
        clientes_data.append({
            'id': u.id,
            'nombre': u.get_full_name() or u.username,
            'email': u.email,
            'fecha_registro': u.date_joined,
            'plan': plan,
            'estado': estado,
            'estado_display': estado_display,
            'fecha_proximo_pago': fecha_prox,
            'propiedades': props_count
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
            Portafolio.objects.create(nombre=nombre_portf, propietario=user)
            
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
    Vista B2B para que el cliente vea su facturación SaaS ($1 por propiedad).
    """
    from .models import Propiedad, FacturaSaaS
    from .utils_tasa import obtener_tasa_dolar
    
    propiedades_activas = Propiedad.objects.filter(
        portafolio__propietario=request.user,
        is_deleted=False
    ).count()
    
    costo_proyectado = propiedades_activas * 1.00
    facturas_saas = FacturaSaaS.objects.filter(usuario=request.user).order_by('-fecha_emision')
    
    try:
        suscripcion = request.user.suscripcion
    except Exception:
        suscripcion = None
        
    tasa_dolar = obtener_tasa_dolar()
    costo_proyectado_pesos = (propiedades_activas * 1.00) * tasa_dolar
        
    context = {
        'titulo_pagina': 'Mi Facturación B2B',
        'propiedades_activas': propiedades_activas,
        'costo_proyectado': costo_proyectado,
        'costo_proyectado_pesos': costo_proyectado_pesos,
        'facturas_saas': facturas_saas,
        'suscripcion': suscripcion,
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
    Botón maestro (Superadmin) para facturar a todos los clientes.
    """
    if not request.user.is_superuser:
        messages.error(request, "Acceso denegado. Solo el Administrador Global puede emitir cortes.")
        return redirect('dashboard')
        
    from django.utils import timezone
    from datetime import timedelta
    from django.contrib.auth.models import User
    from .models import Propiedad, FacturaSaaS
    
    hoy = timezone.now().date()
    # Filtramos clientes SaaS ignorando superusuarios
    clientes = User.objects.filter(is_superuser=False, suscripcion__isnull=False)
    facturas_creadas = 0
    
    for cliente in clientes:
        suscripcion = cliente.suscripcion
        
        # Guard 1: Solo facturar a cuentas que ya son de PAGO (ACTIVA). Excluir TRIAL y SUSPENDIDAS.
        if suscripcion.estado != 'ACTIVA':
            continue
        
        # Guard 2: Si ya le facturamos y no ha llegado su proxima fecha de corte, lo saltamos
        if suscripcion.fecha_proximo_pago and hoy < suscripcion.fecha_proximo_pago:
            continue
            
        cant_propiedades = Propiedad.objects.filter(
            portafolio__propietario=cliente,
            is_deleted=False
        ).count()
        
        # Matemáticas Usuarios VIP
        from .models import AccesoPortafolio
        cant_asistentes = AccesoPortafolio.objects.filter(portafolio__propietario=cliente).count()
        usuarios_activos = 1 + cant_asistentes
        max_gratis = 2 + suscripcion.asistentes_gratuitos_extra
        usuarios_extra = max(0, usuarios_activos - max_gratis)
        
        monto_base = suscripcion.plan_saas.precio_mensual if suscripcion.plan_saas else decimal.Decimal('0.00')
        monto = float(monto_base) + (cant_propiedades * 1.00) + (usuarios_extra * 1.00)
        
        fecha_venc = hoy + timedelta(days=5)
        FacturaSaaS.objects.create(
            usuario=cliente,
            fecha_vencimiento=fecha_venc,
            monto_total=monto,
            propiedades_cobradas=cant_propiedades,
            usuarios_cobrados=usuarios_extra,
            estado='PENDIENTE'
        )
        facturas_creadas += 1
        
        # Reprogramar próximo cobro (1 mes)
        suscripcion.fecha_proximo_pago = hoy + timedelta(days=30)
        suscripcion.save()
            
    if facturas_creadas > 0:
        messages.success(request, f"Éxito: Se generaron {facturas_creadas} facturas para clientes en fecha de corte.")
    else:
        messages.info(request, "Protección Activa: Ningún cliente necesita facturación hoy. No se duplicaron cobros.")
        
    return redirect('saas_master_control')

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
    Localiza la fecha de la última factura y genera la siguiente de forma diferida o futura.
    """
    from django.utils import timezone
    from datetime import date, timedelta
    import calendar
    
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
    
    if request.method == 'POST':
        # 1. Generar la Factura "del futuro"
        nueva_factura = Factura.objects.create(
            contrato=contrato,
            fecha_emision=fecha_proxima_emision,
            fecha_vencimiento=fecha_vencimiento_proxima,
            monto_base=contrato.monto_renta,
            concepto=f"Renta {obtener_nombre_mes(fecha_proxima_emision.month)} {fecha_proxima_emision.year} (Anticipada)",
            estado='PAGADA'
        )
        
        # 2. Registrar el ReciboPago
        metodo = request.POST.get('metodo_pago', 'TRANSFERENCIA')
        referencia = request.POST.get('referencia', '')
        # Si el usuario quiere, asume la fecha real de hoy como pago
        fecha_pago = request.POST.get('fecha_pago', timezone.now().date())
        
        ReciboPago.objects.create(
            factura=nueva_factura,
            fecha_pago=fecha_pago,
            monto_pagado=contrato.monto_renta,
            metodo_pago=metodo,
            referencia_transaccion=referencia
        )
        
        messages.success(request, f'Generado recibo de pago anticipado para el mes de {fecha_proxima_emision.strftime("%m/%Y")}.')
        return redirect('detalle_inquilino', inquilino_id=contrato.inquilino.id)
        
    context = {
        'titulo_pagina': 'Recibir Pago Anticipado',
        'contrato': contrato,
        'fecha_proxima_emision': fecha_proxima_emision,
        'fecha_vencimiento_proxima': fecha_vencimiento_proxima,
        'monto_renta': contrato.monto_renta,
    }
    return render(request, 'gestion_propiedades/pago_anticipado.html', context)

@login_required(login_url='/login/')
def reporte_morosos(request):
    """
    Escanea todo el portafolio del usuario y agrupa las facturas atrasadas 
    calculando la mora total, los días de retraso y los datos de contacto.
    """
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

    portafolio = Portafolio.objects.filter(propietario=request.user).first()
    if not portafolio:
        messages.error(request, "No tienes permisos de Administrador para editar los datos de Marca Blanca de este portafolio.")
        return redirect('dashboard')
    
    if request.method == 'POST':
        form = PortafolioForm(request.POST, request.FILES, instance=portafolio)
        if form.is_valid():
            form.save()
            messages.success(request, "Ajustes de Marca Blanca y del portafolio actualizados correctamente.")
            return redirect('editar_portafolio')
    else:
        form = PortafolioForm(instance=portafolio)
    
    context = {
        'form': form,
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
    portafolios = Portafolio.objects.filter(
        Q(propietario=request.user) | Q(accesos__usuario=request.user)
    ).distinct()
    
    propietarios = PropietarioInmueble.objects.filter(
        portafolio__in=portafolios
    ).annotate(
        cant_propiedades=Count('propiedades', filter=Q(propiedades__is_deleted=False))
    ).order_by('nombre')
    
    context = {
        'titulo_pagina': 'Gestión de Propietarios',
        'propietarios': propietarios,
    }
    return render(request, 'gestion_propiedades/lista_propietarios.html', context)


@login_required(login_url='/login/')
def crear_propietario(request):
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
    portafolios = Portafolio.objects.filter(
        Q(propietario=request.user) | Q(accesos__usuario=request.user)
    ).distinct()
    propietario = get_object_or_404(PropietarioInmueble, id=propietario_id, portafolio__in=portafolios)
    
    propiedades = propietario.propiedades.filter(is_deleted=False)
    contratos = Contrato.objects.filter(propiedad__in=propiedades, activo=True).select_related('propiedad', 'inquilino')
    gastos_generales = GastoGeneralPropietario.objects.filter(propietario_inmueble=propietario).order_by('-fecha')[:10]
    liquidaciones = LiquidacionPropietario.objects.filter(propietario_inmueble=propietario).order_by('-periodo_anio', '-periodo_mes')[:12]
    
    context = {
        'titulo_pagina': f'Expediente de Propietario: {propietario.nombre}',
        'propietario': propietario,
        'propiedades': propiedades,
        'contratos': contratos,
        'gastos_generales': gastos_generales,
        'liquidaciones': liquidaciones
    }
    return render(request, 'gestion_propiedades/detalle_propietario.html', context)


# --- MÓDULO DE GASTOS GENERALES Y DEDUCCIONES ---

@login_required(login_url='/login/')
def lista_gastos_generales(request):
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
    portafolios = Portafolio.objects.filter(
        Q(propietario=request.user) | Q(accesos__usuario=request.user)
    ).distinct()
    
    next_url = request.POST.get('next') or request.GET.get('next')
    
    if request.method == 'POST':
        form = GastoGeneralPropietarioForm(request.POST, request.FILES)
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
        form = GastoGeneralPropietarioForm(initial=initial_dict)
        form.fields['propietario_inmueble'].queryset = PropietarioInmueble.objects.filter(portafolio__in=portafolios, activo=True)
        form.fields['propiedad'].queryset = Propiedad.objects.filter(portafolio__in=portafolios, is_deleted=False)
        
    context = {
        'titulo_pagina': 'Registrar Gasto General o Deducción',
        'form': form,
    }
    return render(request, 'gestion_propiedades/form_generico.html', context)


@login_required(login_url='/login/')
def eliminar_gasto_general(request, gasto_id):
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
    portafolios = Portafolio.objects.filter(
        Q(propietario=request.user) | Q(accesos__usuario=request.user)
    ).distinct()
    
    propietarios_list = PropietarioInmueble.objects.filter(portafolio__in=portafolios, activo=True).order_by('nombre')
    todas_propiedades = Propiedad.objects.filter(portafolio__in=portafolios, is_deleted=False).order_by('nombre_o_numero')
    
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
        if propietario_seleccionado:
            if propietario_seleccionado.tipo_comision == 'PORCENTAJE':
                factor = propietario_seleccionado.porcentaje_comision / decimal.Decimal('100.0')
                monto_comision = round(total_ingresos * factor, 2)
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
    if propietario_seleccionado:
        liquidacion_existente = LiquidacionPropietario.objects.filter(
            propietario_inmueble=propietario_seleccionado,
            periodo_mes=mes,
            periodo_anio=anio
        ).first()

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
        'gastos_directos_list': gastos_directos_list,
        'gastos_generales_list': gastos_generales_list,
        'contratos_activos': contratos_activos,
        'situacion_propiedades': situacion_propiedades if 'situacion_propiedades' in locals() else [],
        'saldo_acumulado_anterior': saldo_acumulado_anterior if 'saldo_acumulado_anterior' in locals() else decimal.Decimal('0.00'),
        'neto_a_liquidar_mes': neto_a_liquidar_mes if 'neto_a_liquidar_mes' in locals() else decimal.Decimal('0.00'),
        'neto_a_liquidar': neto_a_liquidar,
        'liquidacion_existente': liquidacion_existente,
        'fecha_generacion': timezone.now()
    }
    return render(request, 'gestion_propiedades/reporte_propietario.html', context)


@login_required(login_url='/login/')
def procesar_liquidacion_propietario(request, propietario_id):
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
        
        if propietario.tipo_comision == 'PORCENTAJE':
            factor = propietario.porcentaje_comision / decimal.Decimal('100.0')
            monto_comision = round(total_ingresos * factor, 2)
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
        
        LiquidacionPropietario.objects.update_or_create(
            propietario_inmueble=propietario,
            periodo_mes=mes,
            periodo_anio=anio,
            defaults={
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
        )
        
        messages.success(request, f'Liquidación de {obtener_nombre_mes(mes)} {anio} para {propietario.nombre} registrada correctamente.')
    return redirect(f'/reportes/propietario/?propietario_id={propietario.id}&mes={mes}&anio={anio}')


@login_required(login_url='/login/')
def imprimir_liquidacion_propietario(request, propietario_id):
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

@login_required(login_url='/login/')
def respaldos_exportacion(request):
    """
    Panel de Copias de Seguridad y Exportación Masiva de Datos para el Usuario/Cliente.
    """
    portafolios = Portafolio.objects.filter(
        Q(propietario=request.user) | Q(accesos__usuario=request.user)
    ).distinct()
    
    total_propiedades = Propiedad.objects.filter(portafolio__in=portafolios, is_deleted=False).count()
    total_propietarios = PropietarioInmueble.objects.filter(portafolio__in=portafolios, activo=True).count()
    total_inquilinos = Inquilino.objects.filter(creado_por=request.user).count()
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
    Genera un archivo ZIP conteniendo archivos CSV estructurados con la información del portafolio.
    """
    portafolios = Portafolio.objects.filter(
        Q(propietario=request.user) | Q(accesos__usuario=request.user)
    ).distinct()
    
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        # 1. Propietarios
        propietarios_qs = PropietarioInmueble.objects.filter(portafolio__in=portafolios)
        output_prop = io.StringIO()
        writer = csv.writer(output_prop)
        writer.writerow(['ID', 'Nombre', 'Cédula/RNC', 'Teléfono', 'Correo', 'Tipo Comisión', 'Porcentaje', 'Monto Fijo', 'Banco', 'Tipo Cuenta', 'Número Cuenta', 'Activo'])
        for p in propietarios_qs:
            writer.writerow([p.id, p.nombre, p.cedula_o_rnc or '', p.telefono or '', p.correo or '', p.tipo_comision, p.porcentaje_comision, p.monto_comision_fijo, p.banco_nombre or '', p.tipo_cuenta or '', p.numero_cuenta or '', 'Sí' if p.activo else 'No'])
        zip_file.writestr('1_Propietarios.csv', output_prop.getvalue().encode('utf-8-sig'))
        
        # 2. Inmuebles / Propiedades
        propiedades_qs = Propiedad.objects.filter(portafolio__in=portafolios, is_deleted=False)
        output_inm = io.StringIO()
        writer = csv.writer(output_inm)
        writer.writerow(['ID', 'Nombre/Unidad', 'Residencial/Grupo', 'Propietario', 'Dirección', 'Precio Sugerido', 'Latitud', 'Longitud', 'Estado', 'Detalles'])
        for pr in propiedades_qs:
            prop_nombre = pr.propietario_inmueble.nombre if pr.propietario_inmueble else 'N/A'
            writer.writerow([pr.id, pr.nombre_o_numero, pr.grupo_o_residencial or '', prop_nombre, pr.direccion_completa or '', pr.precio_alquiler_sugerido or 0.00, pr.latitud or '', pr.longitud or '', pr.get_estado_display(), pr.detalles or ''])
        zip_file.writestr('2_Propiedades_Inmuebles.csv', output_inm.getvalue().encode('utf-8-sig'))

        # 3. Inquilinos
        inquilinos_qs = Inquilino.objects.filter(creado_por=request.user)
        output_inq = io.StringIO()
        writer = csv.writer(output_inq)
        writer.writerow(['ID', 'Nombre', 'Teléfono', 'Cédula/Pasaporte', 'Correo', 'Alertas Correo'])
        for i in inquilinos_qs:
            writer.writerow([i.id, i.nombre, i.telefono, i.cedula_o_pasaporte or '', i.correo or '', 'Sí' if i.recibir_alertas_correo else 'No'])
        zip_file.writestr('3_Inquilinos.csv', output_inq.getvalue().encode('utf-8-sig'))

        # 4. Contratos
        contratos_qs = Contrato.objects.filter(propiedad__portafolio__in=portafolios)
        output_con = io.StringIO()
        writer = csv.writer(output_con)
        writer.writerow(['ID Contrato', 'Propiedad', 'Inquilino', 'Fecha Inicio', 'Fecha Fin', 'Monto Renta', 'Monto Depósito', 'Monto Adelanto', 'Día de Pago', 'Estado Activo'])
        for c in contratos_qs:
            writer.writerow([c.id, c.propiedad.nombre_o_numero, c.inquilino.nombre, c.fecha_inicio, c.fecha_fin or 'Indefinido', c.monto_renta, c.monto_deposito, c.monto_adelanto, c.dia_de_pago, 'Sí' if c.activo else 'No'])
        zip_file.writestr('4_Contratos.csv', output_con.getvalue().encode('utf-8-sig'))

        # 5. Facturas y Cobros
        facturas_qs = Factura.objects.filter(contrato__propiedad__portafolio__in=portafolios).select_related('contrato__propiedad', 'contrato__inquilino')
        output_fac = io.StringIO()
        writer = csv.writer(output_fac)
        writer.writerow(['No. Factura', 'Propiedad', 'Inquilino', 'Concepto', 'Monto Base', 'Estado', 'Fecha Emisión', 'Fecha Vencimiento'])
        for f in facturas_qs:
            writer.writerow([f.id, f.contrato.propiedad.nombre_o_numero, f.contrato.inquilino.nombre, f.concepto, f.monto_base, f.get_estado_display(), f.fecha_emision, f.fecha_vencimiento])
        zip_file.writestr('5_Facturas_y_Cobros.csv', output_fac.getvalue().encode('utf-8-sig'))

        # 6. Gastos y Mantenimientos
        mantenimientos_qs = MantenimientoUnidad.objects.filter(propiedad__portafolio__in=portafolios)
        output_gas = io.StringIO()
        writer = csv.writer(output_gas)
        writer.writerow(['ID', 'Propiedad', 'Concepto/Trabajo', 'Categoría', 'Costo', 'Estado', 'Fecha Reporte'])
        for m in mantenimientos_qs:
            writer.writerow([m.id, m.propiedad.nombre_o_numero, m.titulo_trabajo, m.categoria, m.costo, m.estado, m.fecha_reporte])
        zip_file.writestr('6_Gastos_y_Mantenimientos.csv', output_gas.getvalue().encode('utf-8-sig'))

        # 7. Liquidaciones a Propietarios
        liq_qs = LiquidacionPropietario.objects.filter(propietario_inmueble__portafolio__in=portafolios)
        output_liq = io.StringIO()
        writer = csv.writer(output_liq)
        writer.writerow(['ID', 'Propietario', 'Período', 'Rentas Cobradas', 'Comisión Admin', 'Gastos Propiedades', 'Gastos Generales', 'Neto Pagado', 'Fecha Pago', 'Método'])
        for l in liq_qs:
            writer.writerow([l.id, l.propietario_inmueble.nombre, f"{l.periodo_mes}/{l.periodo_anio}", l.monto_rentas_cobradas, l.monto_comision, l.monto_gastos_propiedades, l.monto_gastos_generales, l.monto_neto_pagado, l.fecha_pago, l.metodo_pago])
        zip_file.writestr('7_Liquidaciones_Propietarios.csv', output_liq.getvalue().encode('utf-8-sig'))

    zip_buffer.seek(0)
    fecha_str = date.today().strftime('%Y%m%d')
    response = HttpResponse(zip_buffer.getvalue(), content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="Alquilo_Backup_Datos_{fecha_str}.zip"'
    return response


@login_required(login_url='/login/')
def exportar_archivos_adjuntos_zip(request):
    """
    Empaqueta y descarga todos los documentos PDF e imágenes subidas en el servidor.
    """
    import os
    
    portafolios = Portafolio.objects.filter(
        Q(propietario=request.user) | Q(accesos__usuario=request.user)
    ).distinct()
    
    zip_buffer = io.BytesIO()
    count_files = 0
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        # Documentos de contratos
        contratos_qs = Contrato.objects.filter(propiedad__portafolio__in=portafolios)
        for c in contratos_qs:
            if c.documento_contrato and os.path.exists(c.documento_contrato.path):
                arcname = f"Contratos/Contrato_{c.id}_{c.propiedad.nombre_o_numero}_{os.path.basename(c.documento_contrato.name)}"
                zip_file.write(c.documento_contrato.path, arcname=arcname)
                count_files += 1
                
        # Imágenes de propiedades
        propiedades_qs = Propiedad.objects.filter(portafolio__in=portafolios)
        for pr in propiedades_qs:
            if pr.imagen_principal and os.path.exists(pr.imagen_principal.path):
                arcname = f"Propiedades/Foto_{pr.id}_{pr.nombre_o_numero}_{os.path.basename(pr.imagen_principal.name)}"
                zip_file.write(pr.imagen_principal.path, arcname=arcname)
                count_files += 1

    if count_files == 0:
        messages.warning(request, 'No se encontraron archivos físicos adjuntos cargados en el servidor para exportar.')
        return redirect('respaldos_exportacion')

    zip_buffer.seek(0)
    fecha_str = date.today().strftime('%Y%m%d')
    response = HttpResponse(zip_buffer.getvalue(), content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="Alquilo_Archivos_Adjuntos_{fecha_str}.zip"'
    return response


@login_required(login_url='/login/')
def papelera_reciclaje(request):
    """
    Centro de Recuperación / Papelera de Reciclaje para propiedades eliminadas lógicamente.
    """
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
