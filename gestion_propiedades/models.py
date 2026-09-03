from django.db import models
from django.contrib.auth.models import User
import uuid
from datetime import date

class Portafolio(models.Model):
    nombre = models.CharField(max_length=100, help_text="Ej: Inversiones Familiares o Portafolio Principal")
    propietario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='portafolios')
    creado_en = models.DateTimeField(auto_now_add=True)
    
    # Marca Blanca (White-label) opcionales
    eslogan = models.CharField(max_length=200, blank=True, null=True, help_text="Eslogan del negocio")
    direccion_fisica = models.TextField(blank=True, null=True, help_text="Dirección física del negocio")
    telefono_contacto = models.CharField(max_length=50, blank=True, null=True, help_text="Teléfono de contacto")
    logo_empresa = models.ImageField(upload_to='portafolio_logos/', blank=True, null=True, help_text="Logo oficial para imprimir en los recibos PDF")
    
    # Configuración de Fianzas y Adelantos por defecto para este portafolio
    config_meses_deposito = models.IntegerField(default=2, help_text="Cantidad de meses exigidos como depósito por defecto")
    config_meses_adelanto = models.IntegerField(default=0, help_text="Cantidad de meses exigidos por adelantado por defecto")
    # Configuración de Impresión para Hardware Específico
    OPCIONES_IMPRESORA = [
        ('A4', 'Hoja Estándar A4/Carta'),
        ('POS80', 'Ticketera Térmica 80mm'),
        ('POS58', 'Ticketera Térmica 58mm'),
    ]
    formato_impresion = models.CharField(max_length=10, choices=OPCIONES_IMPRESORA, default='A4', help_text="Formato de recibos B2C")

    def __str__(self):
        return self.nombre

class PlanSaaS(models.Model):
    nombre = models.CharField(max_length=50)
    precio_mensual = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    limite_propiedades = models.IntegerField(default=50, help_text="Límite de propiedades permitidas")
    activo = models.BooleanField(default=True)
    
    def __str__(self):
        return f"{self.nombre} - ${self.precio_mensual}"

class ConfiguracionGlobal(models.Model):
    """
    Modelo tipo Singleton para configuraciones que aplican a todo el sistema.
    """
    tasa_dolar_manual = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Si se deja vacío, el sistema usará la tasa automática de internet. Si se coloca un valor, se forzará este valor."
    )
    
    def save(self, *args, **kwargs):
        self.pk = 1 # Garantiza que solo haya un registro
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, created = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Configuración Global del Sistema"

class AvisoSistema(models.Model):
    TIPO_CHOICES = [
        ('info', 'Informativo (Azul)'),
        ('warning', 'Advertencia (Amarillo)'),
        ('danger', 'Urgente (Rojo)'),
        ('success', 'Éxito (Verde)'),
    ]
    mensaje = models.CharField(max_length=255)
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default='info')
    activo = models.BooleanField(default=True, help_text="Si está activo, se mostrará en el header de todos los usuarios.")
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_fin = models.DateTimeField(null=True, blank=True, help_text="Fecha y hora de expiración del aviso")
    
    def __str__(self):
        return f"{self.mensaje} ({self.get_tipo_display()})"

class FacturaSaaS(models.Model):
    ESTADO_CHOICES = [
        ('PENDIENTE', 'Pendiente de Pago'),
        ('PAGADA', 'Pagada'),
        ('VENCIDA', 'Vencida'),
    ]
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='facturas_saas')
    fecha_emision = models.DateField(auto_now_add=True)
    fecha_vencimiento = models.DateField()
    monto_total = models.DecimalField(max_digits=10, decimal_places=2)
    propiedades_cobradas = models.IntegerField(default=0, help_text="Cantidad de propiedades facturadas a $1 c/u")
    usuarios_cobrados = models.IntegerField(default=0, help_text="Cantidad de usuarios extra facturados a $1 c/u")
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='PENDIENTE')
    
    # Podríamos guardar el comprobante de pago del cliente al dueño de Alquilo
    comprobante_pago = models.FileField(upload_to='comprobantes_saas/', blank=True, null=True)

    def __str__(self):
        return f"Factura SaaS #{self.id} - {self.usuario.username} - ${self.monto_total}"

class SuscripcionCliente(models.Model):
    ESTADOS = [
        ('ACTIVA', 'Activa'),
        ('SUSPENDIDA', 'Suspendida (Falta de Pago)'),
        ('CANCELADA', 'Cancelada'),
        ('TRIAL', 'Trial (Prueba)'),
    ]
    
    usuario = models.OneToOneField(User, on_delete=models.CASCADE, related_name='suscripcion')
    # Link to dynamic PlanSaaS model (nuevo)
    plan_saas = models.ForeignKey(PlanSaaS, on_delete=models.SET_NULL, null=True, blank=True, related_name='suscripciones')
    
    # Legacy field
    plan = models.CharField(max_length=20, default='TRIAL')
    
    estado = models.CharField(max_length=20, choices=ESTADOS, default='TRIAL')
    fecha_proximo_pago = models.DateField(blank=True, null=True)
    asistentes_gratuitos_extra = models.IntegerField(default=0, help_text="Otorga asientos VIP adicionales al plan base de 2.")
    
    def __str__(self):
        nombre_plan = self.plan_saas.nombre if self.plan_saas else self.plan
        return f"{self.usuario.username} - {nombre_plan} ({self.estado})"
    
class AccesoPortafolio(models.Model):
    ROLES_CHOICES = [
        ('ADMINISTRADOR', 'Administrador Principal'),
        ('ASISTENTE', 'Asistente (Lectura y Cobros)'),
    ]
    portafolio = models.ForeignKey(Portafolio, on_delete=models.CASCADE, related_name='accesos')
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='portafolios_asignados')
    rol = models.CharField(max_length=20, choices=ROLES_CHOICES, default='ASISTENTE')
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Esto evita que invitemos a la misma persona dos veces al mismo portafolio
        unique_together = ('portafolio', 'usuario')

    def __str__(self):
        return f"{self.usuario.username} - {self.portafolio.nombre} ({self.rol})"

class PropietarioInmueble(models.Model):
    TIPO_COMISION_CHOICES = [
        ('PORCENTAJE', 'Porcentaje sobre Cobro (%)'),
        ('FIJO', 'Monto Fijo Mensual ($)'),
    ]
    
    portafolio = models.ForeignKey(Portafolio, on_delete=models.CASCADE, related_name='propietarios_inmuebles')
    nombre = models.CharField(max_length=150, help_text="Nombre completo o razón social del propietario del inmueble")
    cedula_o_rnc = models.CharField(max_length=50, blank=True, null=True, help_text="Cédula o RNC fiscal")
    telefono = models.CharField(max_length=20, blank=True, null=True)
    correo = models.EmailField(blank=True, null=True)
    direccion = models.TextField(blank=True, null=True)
    
    tipo_comision = models.CharField(max_length=20, choices=TIPO_COMISION_CHOICES, default='PORCENTAJE')
    porcentaje_comision = models.DecimalField(max_digits=5, decimal_places=2, default=0.00, null=True, blank=True, help_text="Ej: 10.00 para 10%")
    monto_comision_fijo = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, null=True, blank=True, help_text="Monto fijo si aplica tipo FIJO")
    
    banco_nombre = models.CharField(max_length=100, blank=True, null=True, help_text="Ej: Banco Popular, Banreservas")
    tipo_cuenta = models.CharField(max_length=50, blank=True, null=True, help_text="Ej: Corriente, Ahorros")
    numero_cuenta = models.CharField(max_length=50, blank=True, null=True, help_text="Número de cuenta para liquidaciones")
    
    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nombre} ({self.portafolio.nombre})"


class Propiedad(models.Model):
    ESTADO_CHOICES = [
        ('DISPONIBLE', 'Disponible'),
        ('OCUPADO', 'Ocupado'),
        ('MANTENIMIENTO', 'En Mantenimiento'),
        ('INACTIVO', 'Archivado / Retirado'),
    ]
    
    portafolio = models.ForeignKey(Portafolio, on_delete=models.CASCADE, related_name='propiedades')
    propietario_inmueble = models.ForeignKey(
        PropietarioInmueble, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='propiedades',
        help_text="Dueño/Propietario del inmueble (Opcional)"
    )
    nombre_o_numero = models.CharField(max_length=100, help_text="Ej: Apt 2B, Casa #4, o Local Comercial 1")
    grupo_o_residencial = models.CharField(max_length=100, blank=True, null=True, help_text="Ej: Residencial Los Pinos (Opcional, para agrupar)")
    direccion_completa = models.TextField(blank=True, null=True)
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='DISPONIBLE')
    detalles = models.TextField(blank=True, null=True, help_text="Ej: 2 habitaciones, 1 baño")
    is_deleted = models.BooleanField(default=False, help_text="Indica si la propiedad fue eliminada lógicamente (Soft Delete)")

    precio_alquiler_sugerido = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, blank=True, null=True, help_text="Precio de alquiler sugerido / publicado ($)")
    latitud = models.DecimalField(max_digits=10, decimal_places=7, blank=True, null=True, help_text="Coordenada GPS Latitud (Ej: 18.486058)")
    longitud = models.DecimalField(max_digits=10, decimal_places=7, blank=True, null=True, help_text="Coordenada GPS Longitud (Ej: -69.931211)")
    imagen_principal = models.ImageField(upload_to='propiedades_fotos/', blank=True, null=True, help_text="Foto principal o fachada de la propiedad")

    def __str__(self):
        if self.grupo_o_residencial:
            return f"{self.grupo_o_residencial} - {self.nombre_o_numero}"
        return self.nombre_o_numero


class ImagenPropiedad(models.Model):
    propiedad = models.ForeignKey(Propiedad, on_delete=models.CASCADE, related_name='imagenes_galeria')
    imagen = models.ImageField(upload_to='propiedades_galeria/')
    titulo_o_descripcion = models.CharField(max_length=150, blank=True, null=True, help_text="Ej: Habitación Principal, Balcón, Cocina")
    subida_en = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Imagen #{self.id} de {self.propiedad.nombre_o_numero}"


class HistorialPrecioPropiedad(models.Model):
    MOTIVO_CHOICES = [
        ('AJUSTE_MERCADO', 'Ajuste de Precio de Lista / Mercado'),
        ('AUMENTO_CONTRATO', 'Aumento por Renovación o Contrato'),
        ('MEJORA_PROPIEDAD', 'Mejora o Remodelación de Unidad'),
        ('OTRO', 'Otro Motivo'),
    ]
    
    propiedad = models.ForeignKey(Propiedad, on_delete=models.CASCADE, related_name='historial_precios')
    precio_anterior = models.DecimalField(max_digits=10, decimal_places=2)
    nuevo_precio = models.DecimalField(max_digits=10, decimal_places=2)
    motivo = models.CharField(max_length=30, choices=MOTIVO_CHOICES, default='AJUSTE_MERCADO')
    notas = models.TextField(blank=True, null=True, help_text="Justificación o detalles del cambio de precio")
    fecha_cambio = models.DateField(default=date.today)
    registrado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha_cambio', '-creado_en']

    def __str__(self):
        return f"{self.propiedad.nombre_o_numero}: ${self.precio_anterior} -> ${self.nuevo_precio} ({self.fecha_cambio})"

class Inquilino(models.Model):
    nombre = models.CharField(max_length=150)
    telefono = models.CharField(max_length=20)
    cedula_o_pasaporte = models.CharField(max_length=50, blank=True, null=True)
    correo = models.EmailField(blank=True, null=True)
    recibir_alertas_correo = models.BooleanField(default=True, help_text="Apaga este interruptor si el inquilino prefiere no recibir correos automáticos de cobranza.")
    creado_por = models.ForeignKey(User, on_delete=models.CASCADE, related_name='inquilinos_registrados', null=True, blank=True)
    usuario_sistema = models.OneToOneField(User, on_delete=models.SET_NULL, null=True, blank=True, help_text="Solo si tendrá acceso al portal web")

    def __str__(self):
        return self.nombre

class PlantillaContrato(models.Model):
    portafolio = models.ForeignKey(Portafolio, on_delete=models.CASCADE, related_name='plantillas_contrato', null=True, blank=True)
    titulo = models.CharField(max_length=150, help_text="Ej: Contrato Estándar, Contrato Comercial")
    contenido = models.TextField(help_text="Contenido HTML del contrato con variables dinámicas")
    es_predeterminada = models.BooleanField(default=False, help_text="Indica si es la plantilla del sistema")
    creada_en = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        if self.es_predeterminada:
            return f"{self.titulo} (Sistema)"
        return f"{self.titulo} - {self.portafolio.nombre}"

class Contrato(models.Model):
    propiedad = models.ForeignKey(Propiedad, on_delete=models.CASCADE, related_name='contratos')
    inquilino = models.ForeignKey(Inquilino, on_delete=models.PROTECT, related_name='contratos')
    
    # --- DATOS DEL ACUERDO Y FACTURACIÓN ---
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField(blank=True, null=True)
    monto_renta = models.DecimalField(max_digits=10, decimal_places=2)
    
    # Tracking de Depósitos y Adelantos retenidos al momento de firmar
    monto_deposito = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="Monto retenido como depósito (Fianza)")
    monto_adelanto = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="Monto cobrado por alquiler adelantado")

    CUSTODIA_DEPOSITO_CHOICES = [
        ('ADMINISTRADORA_CUENTA', 'Retenido en Cuenta de Administradora'),
        ('BANCO_CONSIGNACION', 'En Banco (Consignación)'),
        ('ENTREGADO_PROPIETARIO', 'Entregado al Propietario del Inmueble'),
    ]
    custodia_deposito = models.CharField(
        max_length=30,
        choices=CUSTODIA_DEPOSITO_CHOICES,
        default='ADMINISTRADORA_CUENTA',
        help_text="Ubicación física del depósito de fianza"
    )
    detalles_custodia_deposito = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Ej: Consignación No. 987654 Banco Agrícola/Popular o Entregado al propietario según recibo X"
    )

    dia_de_pago = models.IntegerField(help_text="Día del mes en que se genera la factura (1-31)")
    
    # --- CONFIGURACIÓN DE MORA ---
    dias_gracia = models.IntegerField(default=5, help_text="Días de gracia tras la fecha de pago antes de aplicar mora")
    porcentaje_mora = models.DecimalField(max_digits=5, decimal_places=2, default=0.00, help_text="Ej: 5.00 para cobrar un 5% de mora")
    
    # --- MIGRACIÓN (OPCIONAL) ---
    deuda_renta_migrada = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="Renta acumulada no pagada antes de Alquilo")
    deuda_mora_migrada = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="Moras no pagadas antes de Alquilo")
    
    # --- PLANTILLAS DINÁMICAS ---
    plantilla = models.ForeignKey(PlantillaContrato, on_delete=models.SET_NULL, null=True, blank=True, help_text="Plantilla base utilizada")
    texto_legal_generado = models.TextField(blank=True, null=True, help_text="Copia exacta del texto generado al momento de crear el contrato")
    
    documento_contrato = models.FileField(upload_to='contratos/', blank=True, null=True)
    fotos_entrega = models.FileField(upload_to='entregas_galeria/', blank=True, null=True)
    foto_entrega_2 = models.FileField(upload_to='entregas_galeria/', blank=True, null=True)
    foto_entrega_3 = models.FileField(upload_to='entregas_galeria/', blank=True, null=True)
    foto_entrega_4 = models.FileField(upload_to='entregas_galeria/', blank=True, null=True)
    foto_entrega_5 = models.FileField(upload_to='entregas_galeria/', blank=True, null=True)
    activo = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.propiedad} - {self.inquilino.nombre}"

class Factura(models.Model):
    ESTADO_CHOICES = [
        ('PENDIENTE', 'Pendiente'),
        ('PAGADA', 'Pagada'),
        ('ATRASADA', 'Atrasada'),
        ('ANULADA', 'Anulada'),
    ]

    contrato = models.ForeignKey(Contrato, on_delete=models.CASCADE, related_name='facturas')
    fecha_emision = models.DateField()
    fecha_vencimiento = models.DateField(help_text="Fecha en la que terminan los días de gracia")
    monto_base = models.DecimalField(max_digits=10, decimal_places=2, help_text="Monto original de la renta facturada")
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='PENDIENTE')
    concepto = models.CharField(max_length=255)
    creada_en = models.DateTimeField(auto_now_add=True)

    # Propiedad calculada para saber el total real sumando la renta + moras acumuladas
    @property
    def monto_total_con_mora(self):
        total_moras = sum(mora.monto for mora in self.moras.all())
        return self.monto_base + total_moras

    @property
    def monto_pagado_total(self):
        from django.db.models import Sum
        return self.recibos.aggregate(total=Sum('monto_pagado'))['total'] or 0

    @property
    def saldo_pendiente(self):
        return self.monto_total_con_mora - self.monto_pagado_total

    @property
    def es_prorrateable(self):
        """
        Determina si una factura es elegible para Ajuste manual de Primera Renta.
        Aplica si está pendiente y han transcurrido menos de 45 días desde que inició el contrato.
        """
        if self.estado == 'PENDIENTE' and self.contrato:
            diferencia = self.fecha_emision - self.contrato.fecha_inicio
            return diferencia.days <= 45
        return False

    def __str__(self):
        return f"Factura #{self.id} - {self.contrato.inquilino.nombre} ({self.estado})"

class CargoMora(models.Model):
    factura = models.ForeignKey(Factura, on_delete=models.CASCADE, related_name='moras')
    fecha_aplicacion = models.DateField(auto_now_add=True)
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    # Estos campos aseguran que solo se cobre una vez por mes
    mes_aplicado = models.IntegerField(help_text="Mes en que se generó esta penalidad (1-12)")
    anio_aplicado = models.IntegerField()

    def __str__(self):
        return f"Mora de ${self.monto} a Factura #{self.factura.id}"

class ReciboPago(models.Model):
    METODO_CHOICES = [
        ('TRANSFERENCIA', 'Transferencia Bancaria'),
        ('EFECTIVO', 'Efectivo'),
        ('CHEQUE', 'Cheque'),
        ('OTRO', 'Otro'),
    ]

    factura = models.ForeignKey(Factura, on_delete=models.CASCADE, related_name='recibos')
    fecha_pago = models.DateField()
    monto_pagado = models.DecimalField(max_digits=10, decimal_places=2)
    metodo_pago = models.CharField(max_length=20, choices=METODO_CHOICES, default='TRANSFERENCIA')
    referencia_transaccion = models.CharField(max_length=100, blank=True, null=True)
    comprobante_imagen = models.FileField(upload_to='comprobantes_pago/', blank=True, null=True)
    registrado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='recibos_cobrados', help_text="Usuario que estaba logueado y registró este cobro")
    registrado_en = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Recibo #{self.id} - Factura #{self.factura.id}"

class GastoProgramado(models.Model):
    propiedad = models.ForeignKey(Propiedad, on_delete=models.CASCADE, related_name='gastos_programados')
    concepto = models.CharField(max_length=150, help_text="Ej: Pago de Mantenimiento Residencial")
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    dia_pago = models.IntegerField(default=1, help_text="Día del mes en que se debe pagar este gasto (1-31)")
    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.concepto} - {self.propiedad.nombre_o_numero} - ${self.monto}"

class MantenimientoUnidad(models.Model):
    CATEGORIA_CHOICES = [
        ('REPARACION', 'Reparación'),
        ('PREVENTIVO', 'Mantenimiento Preventivo'),
        ('MEJORA', 'Mejora'),
        ('LIMPIEZA', 'Limpieza y Acondicionamiento'),
        ('OTRO', 'Otros Gastos / Misceláneos'),
    ]
    ESTADO_CHOICES = [
        ('PENDIENTE', 'Pendiente'),
        ('PROGRESO', 'En Progreso'),
        ('COMPLETADO', 'Completado'),
    ]

    propiedad = models.ForeignKey(Propiedad, on_delete=models.CASCADE, related_name='historial_mantenimientos')
    categoria = models.CharField(max_length=20, choices=CATEGORIA_CHOICES)
    descripcion = models.TextField()
    costo = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    fecha_reporte = models.DateField(auto_now_add=True)
    fecha_resolucion = models.DateField(blank=True, null=True)
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='PENDIENTE')
    factura_adjunta = models.FileField(upload_to='comprobantes_mantenimiento/', blank=True, null=True)
    gasto_programado = models.ForeignKey(GastoProgramado, on_delete=models.SET_NULL, null=True, blank=True, related_name='pagos_registrados')

    def __str__(self):
        return f"{self.get_categoria_display()} - {self.propiedad.nombre_o_numero}"
    
class SolicitudAlquiler(models.Model):
    ESTADO_CHOICES = [
        ('BORRADOR', 'Borrador (Configurando preguntas)'),
        ('ENVIADA', 'Link enviado al prospecto'),
        ('RECIBIDA', 'Formulario Completado (Lista para evaluar)'),
        ('APROBADA', 'Aprobada (Lista para contrato)'),
        ('DEVUELTA_PARA_CORRECCION', 'Devuelta para Corrección / Cambiar Garante'),
        ('RECHAZADA', 'Rechazada'),
    ]

    propiedad = models.ForeignKey(Propiedad, on_delete=models.CASCADE, related_name='solicitudes')
    codigo_secreto = models.UUIDField(default=uuid.uuid4, editable=False, unique=True) 
    estado = models.CharField(max_length=30, choices=ESTADO_CHOICES, default='BORRADOR')
    motivo_devolucion = models.TextField(blank=True, null=True, help_text="Nota explicativa enviada al prospecto al devolver el formulario")

    # --- DATOS BÁSICOS (Los llena el prospecto) ---
    nombre_completo = models.CharField(max_length=150, blank=True, null=True)
    cedula = models.CharField(max_length=50, blank=True, null=True)
    telefono = models.CharField(max_length=20, blank=True, null=True)
    estado_civil = models.CharField(max_length=50, blank=True, null=True)
    cantidad_personas = models.IntegerField(blank=True, null=True)
    tiene_mascotas = models.BooleanField(default=False)
    detalles_mascotas = models.CharField(max_length=150, blank=True, null=True, help_text="Ej: 1 perro raza pequeña")
    profesion = models.CharField(max_length=150, blank=True, null=True)
    empresa_trabajo = models.CharField(max_length=150, blank=True, null=True, help_text="Empresa donde labora actualmente")
    telefono_empresa = models.CharField(max_length=20, blank=True, null=True, help_text="Teléfono de la empresa")
    ingresos_mensuales = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)

    # --- DATOS DEL FIADOR / GARANTE ---
    tiene_fiador = models.BooleanField(default=False)
    fiador_nombre = models.CharField(max_length=150, blank=True, null=True)
    fiador_cedula = models.CharField(max_length=50, blank=True, null=True)
    fiador_telefono = models.CharField(max_length=20, blank=True, null=True)
    fiador_correo = models.EmailField(blank=True, null=True)
    fiador_direccion = models.TextField(blank=True, null=True)
    fiador_empresa_trabajo = models.CharField(max_length=150, blank=True, null=True)
    fiador_puesto = models.CharField(max_length=100, blank=True, null=True)
    fiador_ingresos_mensuales = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)

    # --- DOCUMENTOS Y ARCHIVOS ADJUNTOS ---
    adjunto_cedula_solicitante = models.FileField(upload_to='solicitudes_adjuntos/', blank=True, null=True)
    adjunto_ingresos_solicitante = models.FileField(upload_to='solicitudes_adjuntos/', blank=True, null=True)
    adjunto_cedula_fiador = models.FileField(upload_to='solicitudes_adjuntos/', blank=True, null=True)
    adjunto_ingresos_fiador = models.FileField(upload_to='solicitudes_adjuntos/', blank=True, null=True)

    # --- LA MAGIA CONFIGURABLE ---
    # Aquí tú escribes lo que quieras preguntarle antes de enviarle el link
    preguntas_extra = models.TextField(blank=True, null=True, help_text="Escribe aquí las preguntas adicionales que quieres hacerle a este prospecto específico.")
    # Aquí se guardará lo que el prospecto te responda
    respuestas_extra = models.TextField(blank=True, null=True)

    creada_en = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Solicitud para {self.propiedad} - {self.nombre_completo or 'Prospecto Pendiente'}"


class AuditLog(models.Model):
    ACCION_CHOICES = [
        ('CREAR', 'Creó'),
        ('EDITAR', 'Editó'),
        ('ELIMINAR', 'Eliminó'),
    ]

    accion = models.CharField(max_length=10, choices=ACCION_CHOICES)
    modulo = models.CharField(max_length=50, help_text="Ej: Contrato, Factura, ReciboPago, Mantenimiento")
    descripcion = models.TextField()
    usuario = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='auditlogs')
    portafolio = models.ForeignKey(Portafolio, on_delete=models.SET_NULL, null=True, blank=True, related_name='auditlogs')
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"[{self.timestamp:%Y-%m-%d %H:%M}] {self.get_accion_display()} {self.modulo} por {self.usuario}"


class HistorialAumentoRenta(models.Model):
    contrato = models.ForeignKey(Contrato, on_delete=models.CASCADE, related_name='aumentos')
    fecha_aumento = models.DateField(help_text="Fecha en que entra en vigencia el aumento")
    monto_anterior = models.DecimalField(max_digits=10, decimal_places=2)
    nuevo_monto = models.DecimalField(max_digits=10, decimal_places=2)
    usuario = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='aumentos_registrados')
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha_aumento', '-creado_en']

    def __str__(self):
        return f"Aumento Contrato #{self.contrato.id}: ${self.monto_anterior} -> ${self.nuevo_monto}"


from django.utils import timezone

class PublicacionMarketplace(models.Model):
    propiedad = models.OneToOneField(Propiedad, on_delete=models.CASCADE, related_name='publicacion_marketplace')
    titulo = models.CharField(max_length=200, help_text="Ej: Hermoso Apartamento con Vista al Parque")
    descripcion = models.TextField(help_text="Descripción detallada de la propiedad, amenidades y condiciones.")
    precio_renta = models.DecimalField(max_digits=10, decimal_places=2, help_text="Precio de renta mensual en pesos ($)")
    telefono_contacto = models.CharField(max_length=50, help_text="Número de contacto para WhatsApp (Ej: +1809XXXXXXX)")
    creado_por = models.ForeignKey(User, on_delete=models.CASCADE, related_name='publicaciones_marketplace')
    creado_en = models.DateTimeField(auto_now_add=True)
    fecha_activacion = models.DateTimeField(default=timezone.now, help_text="Fecha en que se activó o renovó la publicación")
    activo = models.BooleanField(default=True)

    @property
    def dias_transcurridos(self):
        delta = timezone.now() - self.fecha_activacion
        return delta.days

    @property
    def dias_restantes(self):
        restantes = 45 - self.dias_transcurridos
        return max(0, restantes)

    @property
    def estado_vigencia(self):
        dias = self.dias_transcurridos
        if dias >= 45:
            return 'VENCIDA'
        elif dias >= 40:
            return 'PROXIMA_A_VENCER'
        return 'ACTIVA'

    @property
    def esta_visible(self):
        return self.activo and self.dias_transcurridos < 45

    @property
    def dias_gracia_restantes(self):
        return max(0, 50 - self.dias_transcurridos)

    def delete(self, *args, **kwargs):
        # Delete associated images from disk
        for img in self.imagenes.all():
            img.delete()
        super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.titulo} - {self.propiedad.nombre_o_numero}"


class ImagenPublicacion(models.Model):
    publicacion = models.ForeignKey(PublicacionMarketplace, on_delete=models.CASCADE, related_name='imagenes')
    imagen = models.ImageField(upload_to='marketplace_fotos/')
    creado_en = models.DateTimeField(auto_now_add=True)

    def delete(self, *args, **kwargs):
        # Delete file from storage
        if self.imagen:
            self.imagen.storage.delete(self.imagen.name)
        super().delete(*args, **kwargs)

    def __str__(self):
        return f"Imagen #{self.id} de {self.publicacion.titulo}"


class RegistroProceso(models.Model):
    nombre_proceso = models.CharField(max_length=150, help_text="Ej: Generación de Rentas (Cron) o Generación de Rentas (Manual)")
    fecha_ejecucion = models.DateTimeField(auto_now_add=True)
    exitoso = models.BooleanField(default=True)
    facturas_creadas = models.IntegerField(default=0)
    detalles = models.TextField(blank=True, null=True, help_text="Mensaje de error, advertencia o resumen general")
    ejecutado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, help_text="Usuario que ejecutó, vacío si fue el cron")

    class Meta:
        ordering = ['-fecha_ejecucion']

    def __str__(self):
        estado = "Exitoso" if self.exitoso else "Fallido"
        return f"{self.nombre_proceso} - {self.fecha_ejecucion:%Y-%m-%d %H:%M} ({estado})"


class GastoGeneralPropietario(models.Model):
    CATEGORIA_CHOICES = [
        ('GESTION_LEGAL', 'Gestión Legal / Abogado'),
        ('IMPUESTO_COMISION', 'Impuestos de Comisión / ITBIS / Retenciones'),
        ('HONORARIOS', 'Honorarios Profesionales'),
        ('REPARACION_GENERAL', 'Gastos Generales no asignados a propiedad'),
        ('PUBLICIDAD', 'Publicidad y Mercadeo'),
        ('OTRO', 'Otros Gastos / Deducciones'),
    ]

    portafolio = models.ForeignKey(Portafolio, on_delete=models.CASCADE, related_name='gastos_generales')
    propietario_inmueble = models.ForeignKey(PropietarioInmueble, on_delete=models.CASCADE, null=True, blank=True, related_name='gastos_generales', help_text="Propietario al que aplica el gasto (Opcional)")
    propiedad = models.ForeignKey(Propiedad, on_delete=models.SET_NULL, null=True, blank=True, related_name='gastos_directos_adicionales', help_text="Propiedad específica si aplica (Opcional)")
    
    concepto = models.CharField(max_length=200, help_text="Descripción del gasto o deducción")
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    categoria = models.CharField(max_length=30, choices=CATEGORIA_CHOICES, default='OTRO')
    fecha = models.DateField(default=timezone.now)
    factura_adjunta = models.FileField(upload_to='gastos_comprobantes/', blank=True, null=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    creado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['-fecha', '-creado_en']

    def __str__(self):
        return f"{self.concepto} - ${self.monto} ({self.fecha})"


class LiquidacionPropietario(models.Model):
    ESTADO_CHOICES = [
        ('PENDIENTE', 'Pendiente de Pago'),
        ('PAGADO', 'Liquidado / Pagado'),
    ]
    
    propietario_inmueble = models.ForeignKey(PropietarioInmueble, on_delete=models.CASCADE, related_name='liquidaciones')
    periodo_mes = models.IntegerField(help_text="Mes de liquidación (1-12)")
    periodo_anio = models.IntegerField(help_text="Año de liquidación (Ej: 2026)")
    
    monto_rentas_cobradas = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    monto_comision = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    monto_gastos_propiedades = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    monto_gastos_generales = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    monto_neto_pagado = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="Neto transferido al propietario")
    
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='PENDIENTE')
    fecha_pago = models.DateField(blank=True, null=True)
    metodo_pago = models.CharField(max_length=50, blank=True, null=True, help_text="Ej: Transferencia Bancaria, Cheque, Efectivo")
    referencia_transaccion = models.CharField(max_length=100, blank=True, null=True)
    notas = models.TextField(blank=True, null=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    registrado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        unique_together = ('propietario_inmueble', 'periodo_mes', 'periodo_anio')
        ordering = ['-periodo_anio', '-periodo_mes']

    def __str__(self):
        return f"Liquidación {self.propietario_inmueble.nombre} - {self.periodo_mes}/{self.periodo_anio} (${self.monto_neto_pagado})"


class LiquidacionDepositoInquilino(models.Model):
    ESTADO_CHOICES = [
        ('DEVUELTO', 'Saldo Devuelto al Inquilino'),
        ('RETENIDO_TOTAL', 'Depósito Retenido Totalmente por Deuda/Daños'),
        ('SALDO_PENDIENTE_INQUILINO', 'Inquilino Quedó Debiendo Saldo Adicional'),
    ]
    METODO_CHOICES = [
        ('TRANSFERENCIA', 'Transferencia Bancaria'),
        ('EFECTIVO', 'Efectivo'),
        ('CHEQUE', 'Cheque'),
        ('NO_APLICA', 'No Aplica / Retención Total'),
    ]
    
    contrato = models.OneToOneField(Contrato, on_delete=models.CASCADE, related_name='liquidacion_deposito')
    monto_deposito_original = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="Fianza inicial entregada")
    monto_deduccion_facturas = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="Deducción por rentas o moras pendientes")
    monto_deduccion_danos = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="Deducción por reparaciones de daños")
    monto_neto_devuelto = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="Saldo neto devuelto (+) o a cobrar (-)")
    
    estado = models.CharField(max_length=30, choices=ESTADO_CHOICES, default='DEVUELTO')
    fecha_liquidacion = models.DateField(default=date.today)
    metodo_devolucion = models.CharField(max_length=30, choices=METODO_CHOICES, default='TRANSFERENCIA')
    referencia_pago = models.CharField(max_length=100, blank=True, null=True, help_text="Número de transferencia o cheque")
    detalles_danos = models.TextField(blank=True, null=True, help_text="Explicación detallada de los daños o arreglos aplicados")
    
    registrado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Finiquito Contrato #{self.contrato.id} - Inquilino {self.contrato.inquilino.nombre} (${self.monto_neto_devuelto})"


