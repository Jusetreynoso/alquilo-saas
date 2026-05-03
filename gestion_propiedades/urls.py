from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from . import views_portal
from . import views_equipo
from . import views_plantillas

urlpatterns = [
    # Autenticación B2B SaaS
    path('login/', auth_views.LoginView.as_view(template_name='gestion_propiedades/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),

    # Recuperación de Contraseña
    path('password_reset/', auth_views.PasswordResetView.as_view(template_name='gestion_propiedades/password_reset.html', email_template_name='gestion_propiedades/password_reset_email.html', success_url='/password_reset/done/'), name='password_reset'),
    path('password_reset/done/', auth_views.PasswordResetDoneView.as_view(template_name='gestion_propiedades/password_reset_done.html'), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(template_name='gestion_propiedades/password_reset_confirm.html', success_url='/reset/done/'), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(template_name='gestion_propiedades/password_reset_complete.html'), name='password_reset_complete'),

    # Master Control SaaS
    path('master-control/', views.saas_master_control, name='saas_master_control'),
    path('master-control/cliente/nuevo/', views.crear_cliente_saas, name='crear_cliente_saas'),
    path('master-control/cliente/<int:cliente_id>/editar/', views.editar_suscripcion_saas, name='editar_suscripcion_saas'),
    path('master-control/planes/', views.saas_planes, name='saas_planes'),
    path('master-control/configuracion/', views.editar_configuracion_global, name='editar_configuracion_global'),

    # Sitio Comercial Público (Landing Page y Registro)
    path('', views.inicio_comercial, name='inicio_comercial'),
    path('registro/', views.registro_publico, name='registro_publico'),
    
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
    path('contrato/<int:contrato_id>/pago-anticipado/', views.registrar_pago_anticipado, name='registrar_pago_anticipado'),
    path('contrato/<int:contrato_id>/imprimir-legal/', views.imprimir_contrato_legal, name='imprimir_contrato_legal'),
    
    # Finanzas y Pagos
    path('facturacion/', views.lista_facturas_global, name='lista_facturas_global'),
    path('facturacion/generar-masivo/', views.generar_facturas_masivas, name='generar_facturas_masivas'),
    path('factura/<int:factura_id>/pagar/', views.registrar_pago, name='registrar_pago'),
    path('factura/<int:factura_id>/prorratear/', views.prorratear_factura_inicial, name='prorratear_factura_inicial'),
    path('recibo/<int:recibo_id>/imprimir/', views.imprimir_recibo, name='imprimir_recibo'),
    path('reportes/financiero/', views.reporte_financiero, name='reporte_financiero'),
    path('reportes/rentabilidad/', views.reporte_rentabilidad, name='reporte_rentabilidad'),
    path('reportes/ocupacion/', views.reporte_ocupacion, name='reporte_ocupacion'),
    path('reportes/transparencia/', views.reporte_transparencia, name='reporte_transparencia'),
    path('reportes/morosidad/', views.reporte_morosos, name='reporte_morosos'),
    path('auditoria/', views.vista_auditoria, name='auditoria'),

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
    path('master-control/detector-fugas/', views.saas_detector_fugas, name='saas_detector_fugas'),
    path('master-control/test-email/', views.prueba_correo_saas, name='prueba_correo_saas'),
    path('master-control/factura/<int:factura_id>/pagar/', views.marcar_factura_saas_pagada, name='marcar_factura_saas_pagada'),
    path('mi-suscripcion/', views.mi_suscripcion, name='mi_suscripcion'),
    path('mi-suscripcion/comprobante/<int:factura_id>/', views.subir_comprobante_saas, name='subir_comprobante_saas'),
    
    # --- PORTAL DEL INQUILINO (B2C) ---
    path('portal/login/', views_portal.portal_login, name='portal_login'),
    path('portal/dashboard/', views_portal.portal_dashboard, name='portal_dashboard'),
    path('portal/mantenimiento/', views_portal.portal_mantenimiento, name='portal_mantenimiento'),
    path('portal/logout/', views_portal.portal_logout, name='portal_logout'),

    # --- EQUIPO OPERATIVO Y CONFIG B2B ---
    path('portafolio/ajustes/', views.editar_portafolio, name='editar_portafolio'),
    path('mi-equipo/', views_equipo.mi_equipo, name='mi_equipo'),
    path('mi-equipo/invitar/', views_equipo.crear_asistente, name='crear_asistente'),
    path('mi-equipo/password/<int:usuario_id>/', views_equipo.cambiar_password, name='cambiar_password'),
    path('mi-equipo/revocar/<int:acceso_id>/', views_equipo.eliminar_asistente, name='eliminar_asistente'),
    
    # --- PLANTILLAS DE CONTRATO ---
    path('plantillas/', views_plantillas.lista_plantillas, name='lista_plantillas'),
    path('plantillas/crear/', views_plantillas.editar_plantilla, name='crear_plantilla'),
    path('plantillas/editar/<int:plantilla_id>/', views_plantillas.editar_plantilla, name='editar_plantilla'),
    path('plantillas/eliminar/<int:plantilla_id>/', views_plantillas.eliminar_plantilla, name='eliminar_plantilla'),
]