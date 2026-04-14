from django import forms
from .models import Propiedad, Contrato, Portafolio, MantenimientoUnidad, SolicitudAlquiler, Inquilino, Factura, ReciboPago, SuscripcionCliente, PlanSaaS
from django.db.models import Q

class PortafolioForm(forms.ModelForm):
    class Meta:
        model = Portafolio
        fields = ['nombre', 'eslogan', 'direccion_fisica', 'telefono_contacto', 'config_meses_deposito', 'config_meses_adelanto']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'required': True}),
            'eslogan': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Tu hogar ideal (Opcional)'}),
            'direccion_fisica': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Ej: Av. Principal #123 (Opcional)'}),
            'telefono_contacto': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Opcional'}),
            'config_meses_deposito': forms.NumberInput(attrs={'class': 'form-control'}),
            'config_meses_adelanto': forms.NumberInput(attrs={'class': 'form-control'}),
        }

class PropiedadForm(forms.ModelForm):
    class Meta:
        model = Propiedad
        fields = ['nombre_o_numero', 'grupo_o_residencial', 'direccion_completa', 'detalles', 'estado']
        widgets = {
            'nombre_o_numero': forms.TextInput(attrs={'class': 'form-control'}),
            'grupo_o_residencial': forms.TextInput(attrs={'class': 'form-control'}),
            'direccion_completa': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'detalles': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'estado': forms.Select(attrs={'class': 'form-select'}),
        }

class ContratoForm(forms.ModelForm):
    class Meta:
        model = Contrato
        fields = [
            'propiedad', 'inquilino',
            'fecha_inicio', 'fecha_fin', 'monto_renta', 'monto_deposito', 'monto_adelanto', 'dia_de_pago',
            'dias_gracia', 'porcentaje_mora',
            'documento_contrato', 'fotos_entrega', 'foto_entrega_2', 'foto_entrega_3'
        ]
        widgets = {
            'propiedad': forms.Select(attrs={'class': 'form-select'}),
            'inquilino': forms.Select(attrs={'class': 'form-select'}),
            'fecha_inicio': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'fecha_fin': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'monto_renta': forms.NumberInput(attrs={'class': 'form-control'}),
            'monto_deposito': forms.NumberInput(attrs={'class': 'form-control'}),
            'monto_adelanto': forms.NumberInput(attrs={'class': 'form-control'}),
            'dia_de_pago': forms.NumberInput(attrs={'class': 'form-control'}),
            'dias_gracia': forms.NumberInput(attrs={'class': 'form-control'}),
            'porcentaje_mora': forms.NumberInput(attrs={'class': 'form-control'}),

            'documento_contrato': forms.FileInput(attrs={'class': 'form-control'}),
            'fotos_entrega': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'foto_entrega_2': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'foto_entrega_3': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
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
        # Estos son los campos que llenará el prospecto
        fields = [
            'nombre_completo', 'cedula', 'telefono', 'estado_civil', 
            'cantidad_personas', 'tiene_mascotas', 'detalles_mascotas', 
            'profesion', 'empresa_trabajo', 'telefono_empresa','ingresos_mensuales', 
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
            # Aquí es donde responderá a tus preguntas configuradas:
            'respuestas_extra': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Escribe aquí tus respuestas...'}),
        }

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
        fields = ['plan_saas', 'estado', 'fecha_proximo_pago']
        widgets = {
            'plan_saas': forms.Select(attrs={'class': 'form-select'}),
            'estado': forms.Select(attrs={'class': 'form-select'}),
            'fecha_proximo_pago': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date', 'class': 'form-control'}),
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

from .models import ConfiguracionGlobal
class ConfiguracionGlobalForm(forms.ModelForm):
    class Meta:
        model = ConfiguracionGlobal
        fields = ['tasa_dolar_manual']
        widgets = {
            'tasa_dolar_manual': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Ej. 60.50 (Opcional)'}),
        }