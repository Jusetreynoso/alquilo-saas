from django.db import models
from django.contrib.auth.models import User
import uuid

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

class Propiedad(models.Model):
    ESTADO_CHOICES = [
        ('DISPONIBLE', 'Disponible'),
        ('OCUPADO', 'Ocupado'),
        ('MANTENIMIENTO', 'En Mantenimiento'),
        ('INACTIVO', 'Archivado / Retirado'),
    ]
    
    portafolio = models.ForeignKey(Portafolio, on_delete=models.CASCADE, related_name='propiedades')
    nombre_o_numero = models.CharField(max_length=100, help_text="Ej: Apt 2B, Casa #4, o Local Comercial 1")
    grupo_o_residencial = models.CharField(max_length=100, blank=True, null=True, help_text="Ej: Residencial Los Pinos (Opcional, para agrupar)")
    direccion_completa = models.TextField(blank=True, null=True)
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='DISPONIBLE')
    detalles = models.TextField(blank=True, null=True, help_text="Ej: 2 habitaciones, 1 baño")
    is_deleted = models.BooleanField(default=False, help_text="Indica si la propiedad fue eliminada lógicamente (Soft Delete)")

    def __str__(self):
        if self.grupo_o_residencial:
            return f"{self.grupo_o_residencial} - {self.nombre_o_numero}"
        return self.nombre_o_numero

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

    dia_de_pago = models.IntegerField(help_text="Día del mes en que se genera la factura (1-31)")
    
    # --- CONFIGURACIÓN DE MORA ---
    dias_gracia = models.IntegerField(default=5, help_text="Días de gracia tras la fecha de pago antes de aplicar mora")
    porcentaje_mora = models.DecimalField(max_digits=5, decimal_places=2, default=0.00, help_text="Ej: 5.00 para cobrar un 5% de mora")
    
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

    def __str__(self):
        return f"{self.get_categoria_display()} - {self.propiedad.nombre_o_numero}"
    
class SolicitudAlquiler(models.Model):
    ESTADO_CHOICES = [
        ('BORRADOR', 'Borrador (Configurando preguntas)'),
        ('ENVIADA', 'Link enviado al prospecto'),
        ('RECIBIDA', 'Formulario Completado (Lista para evaluar)'),
        ('APROBADA', 'Aprobada (Lista para contrato)'),
        ('RECHAZADA', 'Rechazada'),
    ]

    propiedad = models.ForeignKey(Propiedad, on_delete=models.CASCADE, related_name='solicitudes')
    # Esto genera un código único (ej: 550e8400-e29b-41d4-a716-446655440000) para que nadie adivine el link
    codigo_secreto = models.UUIDField(default=uuid.uuid4, editable=False, unique=True) 
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='BORRADOR')

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