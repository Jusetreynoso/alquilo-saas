from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.conf import settings
import traceback

class Command(BaseCommand):
    help = 'Ejecuta una prueba forzada del canal SMTP (SendGrid) para validar las credenciales.'

    def add_arguments(self, parser):
        parser.add_argument('destino', type=str, help='Correo electrónico de destino para la prueba.')

    def handle(self, *args, **options):
        correo_prueba = options['destino']
        self.stdout.write(self.style.WARNING(f"🔄 Iniciando prueba de comunicación SMTP hacia: {correo_prueba}"))
        self.stdout.write(f"HOST: {settings.EMAIL_HOST} | PUERTO: {settings.EMAIL_PORT} | USER: {settings.EMAIL_HOST_USER}")

        html_msg = f"""
        <div style="font-family: Arial, sans-serif; background-color: #1a252f; padding: 40px; text-align: center; border-radius: 10px;">
            <h1 style="color: #f39c12;">¡Conexión Exitosa! 🚀</h1>
            <p style="color: white; font-size: 16px;">
                Si estás leyendo este mensaje, significa que el sistema <strong>Alquilo Software</strong>
                se ha conectado correctamente con SendGrid y tus credenciales funcionan al 100%.
            </p>
            <p style="color: #bdc3c7;">El motor automático de cobranza ya puede hacer su trabajo.</p>
        </div>
        """

        try:
            send_mail(
                subject='[Alquilo] 🤖 Prueba de Notificaciones Automáticas',
                message='Esta es una prueba de conexión exitosa al servidor de correos de Alquilo.',
                from_email=None, 
                recipient_list=[correo_prueba],
                html_message=html_msg,
                fail_silently=False,
            )
            self.stdout.write(self.style.SUCCESS(f"✅ ¡ÉXITO ROTUNDO! El correo fue entregado en milisegundos a SendGrid. Revisa la bandeja de entrada de {correo_prueba} (y tu carpeta de Spam por si acaso)."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ FALLO DE CONEXIÓN. Revisa tus variables en Railway."))
            self.stdout.write(self.style.ERROR(str(e)))
            self.stdout.write(traceback.format_exc())
