import os
import logging
from django.core.files.storage import FileSystemStorage
from cloudinary_storage.storage import MediaCloudinaryStorage

logger = logging.getLogger(__name__)


class SmartCloudinaryStorage(MediaCloudinaryStorage):
    """
    Almacenamiento en la nube inteligente, híbrido y tolerante a fallos:
    1. Detecta automáticamente documentos (PDF, DOC, XLS, TXT, etc.) y los almacena como 'raw'
       en Cloudinary, eliminando de raíz el error 'Invalid PDF file' y el Error 500 que ocurría
       al enviarlos al endpoint de imágenes.
    2. Detecta imágenes (PNG, JPG, WEBP, etc.) y las almacena como 'image'.
    3. Detecta videos y los almacena como 'video'.
    4. Fallback tolerante a fallos: Si Cloudinary sufre caídas de red, cuota excedida o rechazo
       por formato, conmuta automáticamente a almacenamiento local (FileSystemStorage)
       garantizando que el registro de pagos o subida de comprobantes NUNCA devuelva Error 500.
    """

    def _get_resource_type(self, name):
        ext = os.path.splitext(name)[1].lower() if name else ''
        if ext in ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.csv', '.txt', '.zip', '.rar']:
            return 'raw'
        if ext in ['.mp4', '.mov', '.avi', '.webm', '.mkv']:
            return 'video'
        return 'image'

    def _save(self, name, content):
        try:
            return super()._save(name, content)
        except Exception as e:
            logger.error(
                f"[SmartCloudinaryStorage] Fallo al subir a Cloudinary ({name}): {e}. "
                "Activando respaldo seguro en almacenamiento local.",
                exc_info=True
            )
            fallback = FileSystemStorage()
            return fallback.save(name, content)

    def url(self, name):
        try:
            # Si el archivo fue guardado localmente por el fallback
            if name and not str(name).startswith('http'):
                fallback = FileSystemStorage()
                if fallback.exists(name):
                    return fallback.url(name)
            return super().url(name)
        except Exception:
            return FileSystemStorage().url(name)
