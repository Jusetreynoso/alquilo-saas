import io
import os
import logging
from PIL import Image, ImageOps
from django.core.files.base import ContentFile

logger = logging.getLogger(__name__)


def optimizar_campo_imagen(instance, field_name, max_dimension=1600, calidad=80):
    """
    Optimiza automáticamente un campo FileField/ImageField de una instancia Django.
    
    Reglas de protección:
    - Solo actúa si hay un archivo NUEVO asignado (campo._committed is False).
    - Si el archivo es un PDF u otro formato de documento, se deja 100% intacto.
    - Corrige automáticamente la rotación EXIF de fotos tomadas en móviles (iPhone/Android).
    - Convierte modos RGBA / Palette a RGB con fondo blanco para guardado JPEG de alta eficiencia.
    - Redimensiona proporcionalmente si ancho o alto superan max_dimension (1600px por defecto).
    - Comprime a JPEG optimizado (calidad 80), logrando reducciones de hasta 90% en peso.
    """
    campo = getattr(instance, field_name, None)
    if not campo:
        return

    # Si ya fue guardado y no se ha modificado en esta petición, no hacer nada
    if getattr(campo, '_committed', True):
        return

    nombre_archivo = campo.name or ''
    ext = os.path.splitext(nombre_archivo)[1].lower()

    # Si es documento no imagen, preservar intacto
    extensiones_excluidas = ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.csv', '.txt', '.zip', '.rar']
    if ext in extensiones_excluidas:
        return

    extensiones_imagen = ['.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.jfif', '.heic']
    if ext and ext not in extensiones_imagen:
        return

    try:
        # Asegurar lectura desde el byte inicial
        if hasattr(campo.file, 'seek'):
            campo.file.seek(0)
            
        img = Image.open(campo.file)

        # 1. Normalizar orientación según sensor de cámara móvil (EXIF)
        img = ImageOps.exif_transpose(img)

        # 2. Manejo de transparencias y canales alfa
        if img.mode in ('RGBA', 'LA', 'P'):
            fondo = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            mask = img.split()[-1] if img.mode in ('RGBA', 'LA') else None
            fondo.paste(img, mask=mask)
            img = fondo
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        # 3. Redimensionamiento proporcional
        ancho, alto = img.size
        if ancho > max_dimension or alto > max_dimension:
            img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

        # 4. Compresión JPEG en buffer de memoria
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=calidad, optimize=True)
        buffer_val = buffer.getvalue()

        # 5. Normalizar nombre con extensión .jpg
        nombre_base = os.path.splitext(os.path.basename(nombre_archivo))[0]
        nuevo_nombre = f"{nombre_base}.jpg"

        # 6. Reemplazar el archivo no confirmado con la versión comprimida
        campo.save(nuevo_nombre, ContentFile(buffer_val), save=False)
        logger.info(f"Imagen '{field_name}' optimizada con éxito ({ancho}x{alto} -> {img.size[0]}x{img.size[1]}, {len(buffer_val)} bytes).")

    except Exception as e:
        logger.warning(f"No se pudo optimizar la imagen del campo '{field_name}': {e}. Se mantendrá el archivo original.")
        try:
            if hasattr(campo.file, 'seek'):
                campo.file.seek(0)
        except Exception:
            pass


def optimizar_campos_modelo(instance, field_names, max_dimension=1600, calidad=80):
    """
    Aplica optimización a múltiples campos de una misma instancia.
    """
    for field in field_names:
        optimizar_campo_imagen(instance, field, max_dimension=max_dimension, calidad=calidad)
