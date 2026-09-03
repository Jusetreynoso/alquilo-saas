import decimal
from django import forms
from .models import Propiedad, Contrato, Portafolio, MantenimientoUnidad, SolicitudAlquiler, Inquilino, Factura, ReciboPago, SuscripcionCliente, PlanSaaS, GastoProgramado, PropietarioInmueble, GastoGeneralPropietario, LiquidacionPropietario, LiquidacionDepositoInquilino, HistorialPrecioPropiedad
from django.db.models import Q

class PortafolioForm(forms.ModelForm):
    class Meta:
        model = Portafolio
        fields = ['nombre', 'eslogan', 'direccion_fisica', 'telefono_contacto', 'logo_empresa', 'formato_impresion', 'config_meses_deposito', 'config_meses_adelanto']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'required': True}),
            'eslogan': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Tu hogar ideal (Opcional)'}),
            'direccion_fisica': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Ej: Av. Principal #123 (Opcional)'}),
            'telefono_contacto': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Opcional'}),
            'logo_empresa': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'formato_impresion': forms.Select(attrs={'class': 'form-select'}),
            'config_meses_deposito': forms.NumberInput(attrs={'class': 'form-control'}),
            'config_meses_adelanto': forms.NumberInput(attrs={'class': 'form-control'}),
        }

class PropiedadForm(forms.ModelForm):
    class Meta:
        model = Propiedad
        fields = [
            'nombre_o_numero', 'grupo_o_residencial', 'propietario_inmueble',
            'precio_alquiler_sugerido', 'direccion_completa', 'latitud', 'longitud',
            'imagen_principal', 'detalles', 'estado'
        ]
        widgets = {
            'nombre_o_numero': forms.TextInput(attrs={'class': 'form-control', 'required': True, 'placeholder': 'Ej: Apt 2B, Casa #4, u Oficina 101'}),
            'grupo_o_residencial': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Torre Vista Mar (Opcional)'}),
            'propietario_inmueble': forms.Select(attrs={'class': 'form-select'}),
            'precio_alquiler_sugerido': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': 'Ej: 25000.00'}),
            'direccion_completa': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Calle, Sector, Ciudad...'}),
            'latitud': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.0000001', 'placeholder': 'Ej: 18.486058'}),
            'longitud': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.0000001', 'placeholder': 'Ej: -69.931211'}),
            'imagen_principal': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'detalles': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Ej: 3 habitaciones, 2 baños, 1 parqueo'}),
            'estado': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['propietario_inmueble'].required = False
        self.fields['precio_alquiler_sugerido'].required = False
        self.fields['latitud'].required = False
        self.fields['longitud'].required = False
        self.fields['imagen_principal'].required = False

class ContratoForm(forms.ModelForm):
    class Meta:
        model = Contrato
        fields = [
            'propiedad', 'inquilino', 'plantilla',
            'fecha_inicio', 'fecha_fin', 'monto_renta', 'monto_deposito', 'custodia_deposito', 'detalles_custodia_deposito', 'monto_adelanto', 'dia_de_pago',
            'dias_gracia', 'porcentaje_mora', 'deuda_renta_migrada', 'deuda_mora_migrada',
            'documento_contrato', 'fotos_entrega', 'foto_entrega_2', 'foto_entrega_3',
            'foto_entrega_4', 'foto_entrega_5'
        ]
        widgets = {
            'propiedad': forms.Select(attrs={'class': 'form-select'}),
            'inquilino': forms.Select(attrs={'class': 'form-select'}),
            'plantilla': forms.Select(attrs={'class': 'form-select'}),
            'fecha_inicio': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'fecha_fin': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'monto_renta': forms.NumberInput(attrs={'class': 'form-control'}),
            'monto_deposito': forms.NumberInput(attrs={'class': 'form-control'}),
            'custodia_deposito': forms.Select(attrs={'class': 'form-select'}),
            'detalles_custodia_deposito': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Certificado #987654 Banco Popular o Entregado al propietario'}),
            'monto_adelanto': forms.NumberInput(attrs={'class': 'form-control'}),
            'dia_de_pago': forms.NumberInput(attrs={'class': 'form-control'}),
            'dias_gracia': forms.NumberInput(attrs={'class': 'form-control'}),
            'porcentaje_mora': forms.NumberInput(attrs={'class': 'form-control'}),
            'deuda_renta_migrada': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '0.00'}),
            'deuda_mora_migrada': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '0.00'}),

            'documento_contrato': forms.FileInput(attrs={'class': 'form-control'}),
            'fotos_entrega': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'foto_entrega_2': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'foto_entrega_3': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'foto_entrega_4': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'foto_entrega_5': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
        }

    def __init__(self, user, *args, **kwargs):
        super(ContratoForm, self).__init__(*args, **kwargs)
        portafolios = Portafolio.objects.filter(Q(propietario=user) | Q(accesos__usuario=user))
        
        if self.instance and self.instance.pk:
            # Modo EDICIÓN: Evitamos que cambien la propiedad, el inquilino y la fecha inicial
            self.fields['propiedad'].queryset = Propiedad.objects.filter(id=self.instance.propiedad.id)
            self.fields['propiedad'].widget.attrs['readonly'] = True
            self.fields['propiedad'].widget.attrs['style'] = 'pointer-events: none; background-color: #e9ecef;'
            
            if 'inquilino' in self.fields:
                self.fields['inquilino'].queryset = Inquilino.objects.filter(id=self.instance.inquilino.id)
                self.fields['inquilino'].widget.attrs['readonly'] = True
                self.fields['inquilino'].widget.attrs['style'] = 'pointer-events: none; background-color: #e9ecef;'
                
            if 'fecha_inicio' in self.fields:
                self.fields['fecha_inicio'].widget.attrs['readonly'] = True
                self.fields['fecha_inicio'].widget.attrs['style'] = 'pointer-events: none; background-color: #e9ecef;'
        else:
            # Modo CREACIÓN NUEVA
            if 'inquilino' in self.fields:
                inquilinos_propios = Inquilino.objects.filter(
                    Q(creado_por=user) | 
                    Q(contratos__propiedad__portafolio__propietario=user) |
                    Q(contratos__propiedad__portafolio__accesos__usuario=user)
                ).distinct().order_by('nombre')
                self.fields['inquilino'].queryset = inquilinos_propios
                self.fields['inquilino'].empty_label = "--- SELECCIONAR INQUILINO EXISTENTE ---"

            self.fields['propiedad'].queryset = Propiedad.objects.filter(portafolio__in=portafolios, estado='DISPONIBLE')
            self.fields['propiedad'].empty_label = "--- SELECCIONAR PROPIEDAD DISPONIBLE ---"
            
        from .models import PlantillaContrato
        self.fields['plantilla'].queryset = PlantillaContrato.objects.filter(
            Q(portafolio__in=portafolios) | Q(es_predeterminada=True)
        )
        self.fields['plantilla'].empty_label = "--- SELECCIONAR PLANTILLA LEGAL ---"
        self.fields['plantilla'].required = False

class InquilinoForm(forms.ModelForm):
    class Meta:
        model = Inquilino
        fields = ['nombre', 'telefono', 'cedula_o_pasaporte', 'correo', 'recibir_alertas_correo']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'required': True}),
            'telefono': forms.TextInput(attrs={'class': 'form-control', 'required': True}),
            'cedula_o_pasaporte': forms.TextInput(attrs={'class': 'form-control'}),
            'correo': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Para enviarle cuenta de cobro y recordatorios'}),
            'recibir_alertas_correo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

class MantenimientoForm(forms.ModelForm):
    class Meta:
        model = MantenimientoUnidad
        fields = ['categoria', 'descripcion', 'costo', 'estado', 'factura_adjunta']
        widgets = {
            'categoria': forms.Select(attrs={'class': 'form-select'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Detalle del problema...'}),
            'costo': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '0.00'}),
            'estado': forms.Select(attrs={'class': 'form-select'}),
            'factura_adjunta': forms.FileInput(attrs={'class': 'form-control'}),
        }

class SolicitudAdminForm(forms.ModelForm):
    class Meta:
        model = SolicitudAlquiler
        fields = ['preguntas_extra']
        widgets = {
            'preguntas_extra': forms.Textarea(attrs={
                'class': 'form-control', 
                'rows': 4, 
                'placeholder': 'Ej: ¿Por qué te mudas de tu residencia actual? ¿Quién será tu garante? (Opcional)'
            }),
        }

class SolicitudPublicaForm(forms.ModelForm):
    class Meta:
        model = SolicitudAlquiler
        fields = [
            'nombre_completo', 'cedula', 'telefono', 'estado_civil', 
            'cantidad_personas', 'tiene_mascotas', 'detalles_mascotas', 
            'profesion', 'empresa_trabajo', 'telefono_empresa', 'ingresos_mensuales', 
            'tiene_fiador', 'fiador_nombre', 'fiador_cedula', 'fiador_telefono', 'fiador_correo',
            'fiador_direccion', 'fiador_empresa_trabajo', 'fiador_puesto', 'fiador_ingresos_mensuales',
            'adjunto_cedula_solicitante', 'adjunto_ingresos_solicitante',
            'adjunto_cedula_fiador', 'adjunto_ingresos_fiador',
            'respuestas_extra'
        ]
        widgets = {
            'nombre_completo': forms.TextInput(attrs={'class': 'form-control', 'required': True}),
            'cedula': forms.TextInput(attrs={'class': 'form-control', 'required': True}),
            'telefono': forms.TextInput(attrs={'class': 'form-control', 'required': True}),
            'estado_civil': forms.TextInput(attrs={'class': 'form-control'}),
            'cantidad_personas': forms.NumberInput(attrs={'class': 'form-control', 'required': True}),
            'tiene_mascotas': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'detalles_mascotas': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: 1 gato pequeño'}),
            'profesion': forms.TextInput(attrs={'class': 'form-control'}),
            'empresa_trabajo': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Banco Popular, Claro, etc.'}),
            'telefono_empresa': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: 809-000-0000'}),
            'ingresos_mensuales': forms.NumberInput(attrs={'class': 'form-control', 'required': True, 'placeholder': '0.00'}),

            'tiene_fiador': forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'id_tiene_fiador', 'onchange': 'toggleFiadorSection()'}),
            'fiador_nombre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nombre completo del fiador'}),
            'fiador_cedula': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Cédula o pasaporte'}),
            'fiador_telefono': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Teléfono de contacto'}),
            'fiador_correo': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Correo del fiador'}),
            'fiador_direccion': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Dirección residencial del fiador'}),
            'fiador_empresa_trabajo': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Empresa donde labora'}),
            'fiador_puesto': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Cargo o puesto laboral'}),
            'fiador_ingresos_mensuales': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),

            'adjunto_cedula_solicitante': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*,application/pdf'}),
            'adjunto_ingresos_solicitante': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*,application/pdf'}),
            'adjunto_cedula_fiador': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*,application/pdf'}),
            'adjunto_ingresos_fiador': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*,application/pdf'}),

            'respuestas_extra': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Escribe aquí tus respuestas...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['fiador_nombre'].required = False
        self.fields['fiador_cedula'].required = False
        self.fields['fiador_telefono'].required = False
        self.fields['fiador_correo'].required = False
        self.fields['fiador_direccion'].required = False
        self.fields['fiador_empresa_trabajo'].required = False
        self.fields['fiador_puesto'].required = False
        self.fields['fiador_ingresos_mensuales'].required = False
        self.fields['adjunto_cedula_solicitante'].required = False
        self.fields['adjunto_ingresos_solicitante'].required = False
        self.fields['adjunto_cedula_fiador'].required = False
        self.fields['adjunto_ingresos_fiador'].required = False

# --- FORMULARIOS B2B SAAS ---

class NuevoClienteSaaSForm(forms.Form):
    nombre = forms.CharField(max_length=100, widget=forms.TextInput(attrs={'class': 'form-control'}))
    apellidos = forms.CharField(max_length=100, widget=forms.TextInput(attrs={'class': 'form-control'}))
    email = forms.EmailField(widget=forms.EmailInput(attrs={'class': 'form-control'}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control'}))
    nombre_portafolio = forms.CharField(max_length=100, required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej. Inversiones García'}), help_text="Se creará uno por defecto si se deja en blanco.")

class EditarSuscripcionForm(forms.ModelForm):
    class Meta:
        model = SuscripcionCliente
        fields = ['plan_saas', 'estado', 'fecha_proximo_pago', 'asistentes_gratuitos_extra']
        widgets = {
            'plan_saas': forms.Select(attrs={'class': 'form-select'}),
            'estado': forms.Select(attrs={'class': 'form-select'}),
            'fecha_proximo_pago': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date', 'class': 'form-control'}),
            'asistentes_gratuitos_extra': forms.NumberInput(attrs={'class': 'form-control'}),
        }

class PlanSaaSForm(forms.ModelForm):
    class Meta:
        model = PlanSaaS
        fields = ['nombre', 'precio_mensual', 'limite_propiedades', 'activo']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'precio_mensual': forms.NumberInput(attrs={'class': 'form-control'}),
            'limite_propiedades': forms.NumberInput(attrs={'class': 'form-control'}),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check-input'})
        }

from .models import ConfiguracionGlobal, PublicacionMarketplace
class ConfiguracionGlobalForm(forms.ModelForm):
    class Meta:
        model = ConfiguracionGlobal
        fields = ['tasa_dolar_manual']
        widgets = {
            'tasa_dolar_manual': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Ej. 60.50 (Opcional)'}),
        }


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.ImageField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput(attrs={'multiple': True, 'class': 'form-control', 'accept': 'image/*'}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            result = [single_file_clean(d, initial) for d in data]
        else:
            result = single_file_clean(data, initial)
        return result


class PublicacionMarketplaceForm(forms.ModelForm):
    imagenes = MultipleImageField(
        required=False,
        label="Subir Fotografías"
    )

    class Meta:
        model = PublicacionMarketplace
        fields = ['titulo', 'descripcion', 'precio_renta', 'telefono_contacto']
        widgets = {
            'titulo': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Espectacular Penthouse con Vista al Mar', 'required': True}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Describe los detalles de la propiedad, amenidades (piscina, balcón, seguridad), etc.', 'required': True}),
            'precio_renta': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Monto mensual en $', 'required': True}),
            'telefono_contacto': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: +18095551234', 'required': True}),
        }

class GastoProgramadoForm(forms.ModelForm):
    class Meta:
        model = GastoProgramado
        fields = ['concepto', 'monto', 'dia_pago', 'activo']
        widgets = {
            'concepto': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Mantenimiento Residencial', 'required': True}),
            'monto': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '0.00', 'required': True}),
            'dia_pago': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 31, 'required': True}),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class PropietarioInmuebleForm(forms.ModelForm):
    propiedades = forms.ModelMultipleChoiceField(
        queryset=Propiedad.objects.none(),
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
        required=False,
        label="Propiedades de este Propietario (Marcar para asignar)"
    )

    class Meta:
        model = PropietarioInmueble
        fields = [
            'nombre', 'cedula_o_rnc', 'telefono', 'correo', 'direccion',
            'tipo_comision', 'porcentaje_comision', 'monto_comision_fijo',
            'banco_nombre', 'tipo_cuenta', 'numero_cuenta', 'activo'
        ]
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'required': True, 'placeholder': 'Ej: Juan Pérez / Inmobiliaria S.A.'}),
            'cedula_o_rnc': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: 001-0000000-0'}),
            'telefono': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: 809-555-0000'}),
            'correo': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'correo@ejemplo.com'}),
            'direccion': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'tipo_comision': forms.Select(attrs={'class': 'form-select'}),
            'porcentaje_comision': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': 'Ej: 10.00'}),
            'monto_comision_fijo': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': 'Ej: 5000.00'}),
            'banco_nombre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Banco Popular'}),
            'tipo_cuenta': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Ahorros / Corriente'}),
            'numero_cuenta': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: 123456789'}),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        portafolios = kwargs.pop('portafolios', None)
        super().__init__(*args, **kwargs)
        self.fields['porcentaje_comision'].required = False
        self.fields['monto_comision_fijo'].required = False
        self.fields['cedula_o_rnc'].required = False
        self.fields['telefono'].required = False
        self.fields['correo'].required = False
        self.fields['direccion'].required = False
        self.fields['banco_nombre'].required = False
        self.fields['tipo_cuenta'].required = False
        self.fields['numero_cuenta'].required = False

        if portafolios is not None:
            self.fields['propiedades'].queryset = Propiedad.objects.filter(portafolio__in=portafolios, is_deleted=False).order_by('nombre_o_numero')
        elif self.instance and self.instance.pk:
            self.fields['propiedades'].queryset = Propiedad.objects.filter(portafolio=self.instance.portafolio, is_deleted=False).order_by('nombre_o_numero')
            self.fields['propiedades'].initial = self.instance.propiedades.filter(is_deleted=False)

    def clean_porcentaje_comision(self):
        val = self.cleaned_data.get('porcentaje_comision')
        return val if val is not None else decimal.Decimal('0.00')

    def clean_monto_comision_fijo(self):
        val = self.cleaned_data.get('monto_comision_fijo')
        return val if val is not None else decimal.Decimal('0.00')


class GastoGeneralPropietarioForm(forms.ModelForm):
    class Meta:
        model = GastoGeneralPropietario
        fields = ['propietario_inmueble', 'propiedad', 'concepto', 'categoria', 'monto', 'fecha', 'factura_adjunta']
        widgets = {
            'propietario_inmueble': forms.Select(attrs={'class': 'form-select'}),
            'propiedad': forms.Select(attrs={'class': 'form-select'}),
            'concepto': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Pago de impuestos por comisión de administración', 'required': True}),
            'categoria': forms.Select(attrs={'class': 'form-select'}),
            'monto': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00', 'required': True}),
            'fecha': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'factura_adjunta': forms.FileInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['propietario_inmueble'].required = False
        self.fields['propiedad'].required = False
        self.fields['factura_adjunta'].required = False


class LiquidacionPropietarioForm(forms.ModelForm):
    class Meta:
        model = LiquidacionPropietario
        fields = ['fecha_pago', 'metodo_pago', 'referencia_transaccion', 'notas']
        widgets = {
            'fecha_pago': forms.DateInput(attrs={'class': 'form-control', 'type': 'date', 'required': True}),
            'metodo_pago': forms.Select(choices=[
                ('TRANSFERENCIA', 'Transferencia Bancaria'),
                ('CHEQUE', 'Cheque'),
                ('EFECTIVO', 'Efectivo'),
                ('OTRO', 'Otro Método'),
            ], attrs={'class': 'form-select', 'required': True}),
            'referencia_transaccion': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: TXN-987654321'}),
            'notas': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Comentarios opcionales sobre la liquidación'}),
        }


class LiquidacionDepositoForm(forms.ModelForm):
    class Meta:
        model = LiquidacionDepositoInquilino
        fields = [
            'monto_deduccion_facturas', 'monto_deduccion_danos',
            'fecha_liquidacion', 'metodo_devolucion', 'referencia_pago', 'detalles_danos'
        ]
        widgets = {
            'monto_deduccion_facturas': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'readonly': True}),
            'monto_deduccion_danos': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00', 'oninput': 'calcularNetoDevolucion()'}),
            'fecha_liquidacion': forms.DateInput(attrs={'class': 'form-control', 'type': 'date', 'required': True}),
            'metodo_devolucion': forms.Select(attrs={'class': 'form-select', 'required': True}),
            'referencia_pago': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: TXN-54321 / No. Cheque'}),
            'detalles_danos': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Explicación detallada de daños o razones de la retención...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['referencia_pago'].required = False
        self.fields['detalles_danos'].required = False


class HistorialPrecioForm(forms.ModelForm):
    class Meta:
        model = HistorialPrecioPropiedad
        fields = ['nuevo_precio', 'motivo', 'fecha_cambio', 'notas']
        widgets = {
            'nuevo_precio': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'required': True, 'placeholder': '0.00'}),
            'motivo': forms.Select(attrs={'class': 'form-select', 'required': True}),
            'fecha_cambio': forms.DateInput(attrs={'class': 'form-control', 'type': 'date', 'required': True}),
            'notas': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Explica el motivo del ajuste o aumento de precio...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['notas'].required = False
