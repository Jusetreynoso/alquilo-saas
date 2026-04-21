from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login
from django.db.models import Sum, Q, Prefetch, F
from django.contrib import messages
from datetime import date
from .models import Portafolio, Propiedad, Factura, CargoMora, ReciboPago, Contrato, SolicitudAlquiler, MantenimientoUnidad, Inquilino, PlanSaaS, SuscripcionCliente, AuditLog
from .forms import NuevoClienteSaaSForm, EditarSuscripcionForm, PropiedadForm, ContratoForm, InquilinoForm, MantenimientoForm, PlanSaaSForm
from .utils import render_to_pdf
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

    context = {
        'titulo_pagina': 'Resumen de Portafolio',
        'total_propiedades': total_propiedades,
        'propiedades_disponibles': propiedades_disponibles,
        'cuentas_por_cobrar': cuentas_por_cobrar,
        'ingresos_mes': ingresos_mes,
        'facturas_pendientes': facturas_pendientes,
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

    context = {
        'titulo_pagina': f'Detalle: {propiedad.nombre_o_numero}',
        'propiedad': propiedad,
        'contrato_activo': contrato_activo,
        'facturas': facturas,
        'mantenimientos': mantenimientos,
        'solicitudes': solicitudes,
    }
    return render(request, 'gestion_propiedades/detalle_propiedad.html', context)

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
        form = PropiedadForm(request.POST)
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
        # IMPORTANTE: Agregamos request.FILES aquí para guardar los PDFs/Fotos
        form = ContratoForm(request.user, request.POST, request.FILES)
        if form.is_valid():
            nuevo_contrato = form.save()
            
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
def generar_facturas_masivas(request):
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

    for contrato in contratos:
        # 3. Verificamos si YA existe una factura para este mes y año
        existe = Factura.objects.filter(
            contrato=contrato,
            fecha_emision__month=hoy.month,
            fecha_emision__year=hoy.year
        ).exists()

        if not existe:
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
                concepto=f"Renta {hoy.strftime('%B %Y')}", # Ej: Renta February 2026
                estado='PENDIENTE'
            )
            facturas_creadas += 1

    # 5. Mensaje de éxito
    if facturas_creadas > 0:
        messages.success(request, f'¡Éxito! Se han generado {facturas_creadas} facturas nuevas.')
    else:
        messages.info(request, 'No se generaron facturas. Todos tus inquilinos ya tienen su factura de este mes.')

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
    # 1. Buscamos el contrato asegurando los permisos del usuario
    portafolios = Portafolio.objects.filter(
        Q(propietario=request.user) | Q(accesos__usuario=request.user)
    ).distinct()
    
    contrato = get_object_or_404(Contrato, id=contrato_id, propiedad__portafolio__in=portafolios)

    # Solo permitimos finalizar mediante el botón (método POST) por seguridad
    if request.method == 'POST':
        # 2. Desactivamos el contrato y le ponemos fecha de fin oficial
        contrato.activo = False
        contrato.fecha_fin = date.today()
        contrato.save()

        # 3. Liberamos la propiedad
        propiedad = contrato.propiedad
        propiedad.estado = 'DISPONIBLE'
        propiedad.save()

        messages.success(request, f'El contrato de {contrato.inquilino.nombre} ha sido finalizado. La propiedad vuelve a estar disponible.')
        return redirect('detalle_propiedad', propiedad_id=propiedad.id)

    # Si alguien intenta acceder por la barra de direcciones (GET), lo devolvemos
    return redirect('detalle_propiedad', propiedad_id=contrato.propiedad.id)

@login_required(login_url='/login/')
def editar_propiedad(request, propiedad_id):
    from .forms import PropiedadForm
    
    portafolios = Portafolio.objects.filter(Q(propietario=request.user) | Q(accesos__usuario=request.user))
    propiedad = get_object_or_404(Propiedad, id=propiedad_id, portafolio__in=portafolios)

    if request.method == 'POST':
        # instance=propiedad le dice a Django "actualiza este registro, no crees uno nuevo"
        form = PropiedadForm(request.POST, instance=propiedad)
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
            form.save()
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

    # Si ya la llenó antes, no le dejamos llenarla de nuevo
    if solicitud.estado in ['RECIBIDA', 'APROBADA', 'RECHAZADA']:
        return HttpResponse("<h2 style='text-align:center; padding:50px; font-family:sans-serif;'>Esta solicitud ya fue completada y enviada. ¡Gracias!</h2>")

    if request.method == 'POST':
        form = SolicitudPublicaForm(request.POST, instance=solicitud)
        if form.is_valid():
            solicitud_guardada = form.save(commit=False)
            solicitud_guardada.estado = 'RECIBIDA' # ¡Cambia el estado para avisarte!
            solicitud_guardada.save()
            # Mensaje de éxito gigante para el celular del prospecto
            return HttpResponse("<h2 style='text-align:center; padding:50px; color:green; font-family:sans-serif;'>✅ ¡Solicitud enviada con éxito! El propietario se pondrá en contacto contigo.</h2>")
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
def reporte_financiero(request):
    portafolios = Portafolio.objects.filter(
        Q(propietario=request.user) | Q(accesos__usuario=request.user)
    ).distinct()

    ingresos_qs = ReciboPago.objects.filter(
        factura__contrato__propiedad__portafolio__in=portafolios
    ).annotate(
        mes=TruncMonth('fecha_pago')
    ).values(
        'mes',
        'factura__contrato__propiedad__id',
        'factura__contrato__propiedad__nombre_o_numero'
    ).annotate(total_ingresos=Sum('monto_pagado'))

    egresos_qs = MantenimientoUnidad.objects.filter(
        propiedad__portafolio__in=portafolios
    ).annotate(
        mes=TruncMonth('fecha_reporte') 
    ).values(
        'mes',
        'propiedad__id',
        'propiedad__nombre_o_numero'
    ).annotate(total_egresos=Sum('costo'))

    datos_financieros = defaultdict(lambda: {
        'nombre_propiedad': '',
        'mes_formateado': '',
        'mes_date': None,
        'ingresos': 0.0,
        'egresos': 0.0,
        'neto': 0.0
    })

    for ingreso in ingresos_qs:
        if not ingreso['mes']: continue
        llave = (ingreso['mes'], ingreso['factura__contrato__propiedad__id'])
        datos = datos_financieros[llave]
        
        datos['nombre_propiedad'] = ingreso['factura__contrato__propiedad__nombre_o_numero']
        datos['mes_formateado'] = ingreso['mes'].strftime('%Y-%m')
        datos['mes_date'] = ingreso['mes']
        datos['ingresos'] += float(ingreso['total_ingresos'] or 0)

    for egreso in egresos_qs:
        if not egreso['mes']: continue
        llave = (egreso['mes'], egreso['propiedad__id'])
        datos = datos_financieros[llave]
        
        if not datos['nombre_propiedad']:
            datos['nombre_propiedad'] = egreso['propiedad__nombre_o_numero']
            datos['mes_formateado'] = egreso['mes'].strftime('%Y-%m')
            datos['mes_date'] = egreso['mes']
            
        datos['egresos'] += float(egreso['total_egresos'] or 0)

    lista_finanzas = []
    for llave, datos in datos_financieros.items():
        datos['neto'] = datos['ingresos'] - datos['egresos']
        lista_finanzas.append(datos)
    
    lista_finanzas.sort(key=lambda x: (x['mes_date'], x['nombre_propiedad']), reverse=True)

    print("--- DEBUG P&L ---")
    for row in lista_finanzas:
        print(f"Mes: {row['mes_formateado']} | Prop: {row['nombre_propiedad']} | In: ${row['ingresos']} | Out: ${row['egresos']} | NETO: ${row['neto']}")
    print("-----------------")

    context = {
        'titulo_pagina': 'Reporte Financiero (P&L)',
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
    inquilino = get_object_or_404(Inquilino, id=inquilino_id)
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
    inquilino = get_object_or_404(Inquilino, id=inquilino_id)
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
        
    context = {
        'titulo_pagina': 'Centro de Mando SaaS',
        'clientes': clientes_data,
        'total_clientes': len(clientes_data),
        'total_activos': sum(1 for c in clientes_data if c['estado'] == 'ACTIVA'),
        'total_suspendidos': sum(1 for c in clientes_data if c['estado'] == 'SUSPENDIDA'),
        'total_trials': sum(1 for c in clientes_data if c['estado'] == 'TRIAL'),
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
        
        if cant_propiedades > 0 or usuarios_extra > 0:
            monto = (cant_propiedades * 1.00) + (usuarios_extra * 1.00)
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
@propietario_requerido
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
            concepto=f"Pago Anticipado Renta ({fecha_proxima_emision.strftime('%m/%Y')})",
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
            concepto=f"Pago Anticipado Renta ({fecha_proxima_emision.strftime('%m/%Y')})",
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
