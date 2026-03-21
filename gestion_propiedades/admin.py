from django.contrib import admin
from .models import Portafolio, Propiedad, Contrato, Factura, CargoMora, ReciboPago, MantenimientoUnidad, SuscripcionCliente, PlanSaaS, AvisoSistema

# Personalizando los títulos del panel de Django para "Alquilo"
admin.site.site_header = "Administración Alquilo"
admin.site.site_title = "Portal Alquilo"
admin.site.index_title = "Panel de Control"

@admin.register(Portafolio)
class PortafolioAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'propietario', 'config_meses_deposito', 'config_meses_adelanto', 'creado_en')
    search_fields = ('nombre',)

@admin.register(Propiedad)
class PropiedadAdmin(admin.ModelAdmin):
    # Mostramos el grupo/residencial para que sea fácil identificar si es del complejo de 32 o una casa suelta
    list_display = ('nombre_o_numero', 'grupo_o_residencial', 'portafolio', 'estado')
    list_filter = ('estado', 'portafolio', 'grupo_o_residencial')
    search_fields = ('nombre_o_numero', 'grupo_o_residencial', 'direccion_completa')

@admin.register(Contrato)
class ContratoAdmin(admin.ModelAdmin):
    list_display = ('propiedad', 'inquilino', 'monto_renta', 'monto_deposito', 'dia_de_pago', 'activo')
    list_filter = ('activo', 'dia_de_pago')
    search_fields = ('inquilino__nombre', 'propiedad__nombre_o_numero', 'inquilino__cedula_o_pasaporte')

@admin.register(Factura)
class FacturaAdmin(admin.ModelAdmin):
    # Aquí llamamos a la propiedad calculada "monto_total_con_mora" para ver el monto real a cobrar
    list_display = ('id', 'contrato', 'concepto', 'fecha_emision', 'monto_base', 'monto_total_con_mora', 'estado')
    list_filter = ('estado', 'fecha_emision')
    search_fields = ('contrato__inquilino__nombre', 'concepto')

@admin.register(CargoMora)
class CargoMoraAdmin(admin.ModelAdmin):
    list_display = ('id', 'factura', 'monto', 'mes_aplicado', 'anio_aplicado', 'fecha_aplicacion')
    list_filter = ('mes_aplicado', 'anio_aplicado')
    search_fields = ('factura__contrato__inquilino__nombre',)

@admin.register(ReciboPago)
class ReciboPagoAdmin(admin.ModelAdmin):
    list_display = ('id', 'factura', 'fecha_pago', 'monto_pagado', 'metodo_pago')
    list_filter = ('metodo_pago', 'fecha_pago')
    search_fields = ('factura__contrato__inquilino__nombre', 'referencia_transaccion')

@admin.register(MantenimientoUnidad)
class MantenimientoAdmin(admin.ModelAdmin):
    list_display = ('propiedad', 'categoria', 'estado', 'costo', 'fecha_reporte')
    list_filter = ('estado', 'categoria')
    search_fields = ('propiedad__nombre_o_numero', 'descripcion')

@admin.register(SuscripcionCliente)
class SuscripcionClienteAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'plan_saas', 'estado', 'fecha_proximo_pago')
    list_filter = ('estado', 'plan_saas')
    search_fields = ('usuario__username', 'usuario__email')

@admin.register(PlanSaaS)
class PlanSaaSAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'precio_mensual', 'limite_propiedades', 'activo')

@admin.register(AvisoSistema)
class AvisoSistemaAdmin(admin.ModelAdmin):
    list_display = ('mensaje', 'tipo', 'activo', 'fecha_creacion')