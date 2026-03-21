from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    # Autenticación B2B SaaS
    path('login/', auth_views.LoginView.as_view(template_name='gestion_propiedades/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),

    # Master Control SaaS
    path('master-control/', views.saas_master_control, name='saas_master_control'),
    path('master-control/cliente/nuevo/', views.crear_cliente_saas, name='crear_cliente_saas'),
    path('master-control/cliente/<int:cliente_id>/editar/', views.editar_suscripcion_saas, name='editar_suscripcion_saas'),
    path('master-control/planes/', views.saas_planes, name='saas_planes'),

    # Sitio Comercial Público (Landing Page)
    path('', views.inicio_comercial, name='inicio_comercial'),
    
    # Panel Principal Interno
    path('dashboard/', views.dashboard, name='dashboard'),
    
    # Propiedades
    path('propiedades/', views.lista_propiedades, name='lista_propiedades'),
    path('propiedades/crear/', views.crear_propiedad, name='crear_propiedad'),
    path('propiedad/<int:propiedad_id>/', views.detalle_propiedad, name='detalle_propiedad'),
    path('propiedad/<int:propiedad_id>/editar/', views.editar_propiedad, name='editar_propiedad'),
    path('propiedad/<int:propiedad_id>/eliminar/', views.eliminar_propiedad, name='eliminar_propiedad'),
    path('propiedad/<int:propiedad_id>/gasto/nuevo/', views.registrar_gasto, name='registrar_gasto'),

    # Contratos
    path('contratos/', views.lista_contratos, name='lista_contratos'),
    path('contratos/crear/', views.crear_contrato, name='crear_contrato'),
    path('contrato/<int:contrato_id>/editar/', views.editar_contrato, name='editar_contrato'), # NUEVA
    path('contrato/<int:contrato_id>/finalizar/', views.finalizar_contrato, name='finalizar_contrato'),
    
    # Finanzas y Pagos
    path('facturacion/', views.lista_facturas_global, name='lista_facturas_global'),
    path('facturacion/generar-masivo/', views.generar_facturas_masivas, name='generar_facturas_masivas'),
    path('factura/<int:factura_id>/pagar/', views.registrar_pago, name='registrar_pago'),
    path('recibo/<int:recibo_id>/imprimir/', views.imprimir_recibo, name='imprimir_recibo'),
    path('finanzas/reporte/', views.reporte_financiero, name='reporte_financiero'),

    # Rutas limpias
    path('propiedad/<int:propiedad_id>/solicitud/nueva/', views.generar_solicitud, name='generar_solicitud'),

    path('solicitud/<int:solicitud_id>/ver/', views.ver_solicitud, name='ver_solicitud'),

    path('solicitud/<uuid:codigo_secreto>/', views.solicitud_publica, name='solicitud_publica'),

    # Mantenimientos (Helpdesk)
    path('mantenimientos/', views.lista_mantenimientos_global, name='lista_mantenimientos_global'),

    # Inquilinos
    path('inquilinos/', views.lista_inquilinos, name='lista_inquilinos'),
    path('inquilinos/crear/', views.crear_inquilino, name='crear_inquilino'),
    path('inquilino/<int:inquilino_id>/', views.detalle_inquilino, name='detalle_inquilino'),
    path('inquilino/<int:inquilino_id>/editar/', views.editar_inquilino, name='editar_inquilino'),
    
    # SaaS Core
    path('aviso-pago/', views.aviso_pago, name='aviso_pago'),
    path('master-control/', views.saas_master_control, name='saas_master_control'),
    path('master-control/cliente/nuevo/', views.crear_cliente_saas, name='crear_cliente_saas'),
    path('master-control/cliente/<int:cliente_id>/editar/', views.editar_suscripcion_saas, name='editar_suscripcion_saas'),
    path('master-control/generar-corte/', views.generar_corte_saas, name='generar_corte_saas'),
    path('master-control/recaudacion/', views.saas_facturacion, name='saas_facturacion'),
    path('master-control/factura/<int:factura_id>/pagar/', views.marcar_factura_saas_pagada, name='marcar_factura_saas_pagada'),
    path('mi-suscripcion/', views.mi_suscripcion, name='mi_suscripcion'),
]