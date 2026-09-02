from django.contrib import admin
from .models import Portafolio, Propiedad, Contrato, Factura, CargoMora, ReciboPago, MantenimientoUnidad, SuscripcionCliente, PlanSaaS, AvisoSistema, Inquilino, HistorialAumentoRenta, PropietarioInmueble, GastoGeneralPropietario, LiquidacionPropietario, LiquidacionDepositoInquilino, HistorialPrecioPropiedad

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
    list_display = ('nombre_o_numero', 'grupo_o_residencial', 'portafolio', 'precio_alquiler_sugerido', 'estado', 'latitud', 'longitud')
    list_filter = ('estado', 'portafolio', 'grupo_o_residencial')
    search_fields = ('nombre_o_numero', 'grupo_o_residencial', 'direccion_completa')

@admin.register(HistorialPrecioPropiedad)
class HistorialPrecioPropiedadAdmin(admin.ModelAdmin):
    list_display = ('propiedad', 'precio_anterior', 'nuevo_precio', 'motivo', 'fecha_cambio', 'registrado_por')
    list_filter = ('motivo', 'fecha_cambio')
    search_fields = ('propiedad__nombre_o_numero', 'notas')

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


@admin.register(Inquilino)
class InquilinoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'telefono', 'correo', 'cedula_o_pasaporte', 'recibir_alertas_correo')
    search_fields = ('nombre', 'telefono', 'correo', 'cedula_o_pasaporte')


@admin.register(HistorialAumentoRenta)
class HistorialAumentoRentaAdmin(admin.ModelAdmin):
    list_display = ('contrato', 'fecha_aumento', 'monto_anterior', 'nuevo_monto', 'usuario', 'creado_en')
    list_filter = ('fecha_aumento', 'creado_en')
    search_fields = ('contrato__inquilino__nombre', 'usuario__username')

from .models import PublicacionMarketplace, ImagenPublicacion, RegistroProceso, PropietarioInmueble, GastoGeneralPropietario, LiquidacionPropietario

@admin.register(PropietarioInmueble)
class PropietarioInmuebleAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'portafolio', 'cedula_o_rnc', 'tipo_comision', 'porcentaje_comision', 'monto_comision_fijo', 'activo')
    list_filter = ('activo', 'portafolio', 'tipo_comision')
    search_fields = ('nombre', 'cedula_o_rnc', 'telefono', 'correo')

@admin.register(GastoGeneralPropietario)
class GastoGeneralPropietarioAdmin(admin.ModelAdmin):
    list_display = ('concepto', 'portafolio', 'propietario_inmueble', 'propiedad', 'categoria', 'monto', 'fecha')
    list_filter = ('categoria', 'fecha', 'portafolio')
    search_fields = ('concepto', 'propietario_inmueble__nombre')

@admin.register(LiquidacionPropietario)
class LiquidacionPropietarioAdmin(admin.ModelAdmin):
    list_display = ('propietario_inmueble', 'periodo_mes', 'periodo_anio', 'monto_rentas_cobradas', 'monto_neto_pagado', 'estado', 'fecha_pago')
    list_filter = ('estado', 'periodo_anio', 'periodo_mes')
    search_fields = ('propietario_inmueble__nombre', 'referencia_transaccion')

@admin.register(LiquidacionDepositoInquilino)
class LiquidacionDepositoInquilinoAdmin(admin.ModelAdmin):
    list_display = ('contrato', 'monto_deposito_original', 'monto_deduccion_facturas', 'monto_deduccion_danos', 'monto_neto_devuelto', 'estado', 'fecha_liquidacion')
    list_filter = ('estado', 'metodo_devolucion', 'fecha_liquidacion')
    search_fields = ('contrato__inquilino__nombre', 'contrato__propiedad__nombre_o_numero', 'referencia_pago')

@admin.register(PublicacionMarketplace)
class PublicacionMarketplaceAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'propiedad', 'precio_renta', 'telefono_contacto', 'creado_por', 'fecha_activacion', 'activo')
    list_filter = ('activo', 'fecha_activacion')
    search_fields = ('titulo', 'descripcion', 'telefono_contacto', 'propiedad__nombre_o_numero')

@admin.register(ImagenPublicacion)
class ImagenPublicacionAdmin(admin.ModelAdmin):
    list_display = ('id', 'publicacion', 'imagen', 'creado_en')

@admin.register(RegistroProceso)
class RegistroProcesoAdmin(admin.ModelAdmin):
    list_display = ('nombre_proceso', 'fecha_ejecucion', 'exitoso', 'facturas_creadas', 'ejecutado_por')
    list_filter = ('exitoso', 'fecha_ejecucion', 'nombre_proceso')
    search_fields = ('nombre_proceso', 'detalles')

