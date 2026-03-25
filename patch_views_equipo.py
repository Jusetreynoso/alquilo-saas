import os

path = r"C:\Proyectos\sistema_alquilo\gestion_propiedades\views.py"
with open(path, "r", encoding="utf-8") as f:
    text = f.read()

# 1. Add decorator import
if "from .utils_rbac import propietario_requerido" not in text:
    text = text.replace("from django.db.models.functions import TruncMonth", "from django.db.models.functions import TruncMonth\nfrom .utils_rbac import propietario_requerido")

# 2. Add decorator to crear_propiedad
target_crear = "@login_required(login_url='/login/')\ndef crear_propiedad(request):"
replacement_crear = "@login_required(login_url='/login/')\n@propietario_requerido  # ESCUDO RBAC (Solo admins)\ndef crear_propiedad(request):"

if replacement_crear not in text:
    text = text.replace(target_crear, replacement_crear)

# 3. Add decorator to eliminar_propiedad and its code if not exists
if "def eliminar_propiedad(" not in text:
    bloque_eliminar = """
@login_required(login_url='/login/')
@propietario_requerido  # ESCUDO RBAC
def eliminar_propiedad(request, propiedad_id):
    propiedad = get_object_or_404(Propiedad, id=propiedad_id, portafolio__propietario=request.user)
    if propiedad.contratos.filter(activo=True).exists():
        messages.error(request, "No puedes eliminar una propiedad que tiene un contrato activo.")
        return redirect('detalle_propiedad', propiedad_id=propiedad.id)
    
    propiedad.delete()
    messages.success(request, "Propiedad eliminada exitosamente del portafolio.")
    return redirect('lista_propiedades')
"""
    text += bloque_eliminar

# 4. Hide "Mi Suscripcion" SaaS views behind the shield
target_saas1 = "@login_required(login_url='/login/')\ndef saas_facturacion(request):"
replacement_saas1 = "@login_required(login_url='/login/')\n@propietario_requerido\ndef saas_facturacion(request):"
text = text.replace(target_saas1, replacement_saas1)

target_saas2 = "@login_required(login_url='/login/')\ndef mi_suscripcion(request):"
replacement_saas2 = "@login_required(login_url='/login/')\n@propietario_requerido\ndef mi_suscripcion(request):"
text = text.replace(target_saas2, replacement_saas2)

with open(path, "w", encoding="utf-8") as f:
    f.write(text)

print("Views.py exitosamente parcheado con escudos de Equipo B2B.")
