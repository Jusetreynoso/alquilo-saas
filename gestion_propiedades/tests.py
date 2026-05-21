from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from datetime import date, timedelta
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
import os
from .models import Portafolio, Propiedad, Inquilino, Contrato, HistorialAumentoRenta, AuditLog, PlanSaaS, SuscripcionCliente, PublicacionMarketplace, ImagenPublicacion

class AlquiloTests(TestCase):
    def setUp(self):
        # Create users
        self.user1 = User.objects.create_user(username='propietario1', password='password123')
        self.user2 = User.objects.create_user(username='propietario2', password='password123')
        
        # Create Plan
        self.plan = PlanSaaS.objects.create(nombre='Plan Pro', precio_mensual=10.00, limite_propiedades=100, activo=True)
        
        # Create SuscripcionCliente for both users to bypass SuscripcionMiddleware redirects
        SuscripcionCliente.objects.create(usuario=self.user1, plan_saas=self.plan, estado='ACTIVA')
        SuscripcionCliente.objects.create(usuario=self.user2, plan_saas=self.plan, estado='ACTIVA')
        
        # Create portafolios
        self.portafolio1 = Portafolio.objects.create(nombre='Portafolio 1', propietario=self.user1)
        self.portafolio2 = Portafolio.objects.create(nombre='Portafolio 2', propietario=self.user2)
        
        # Create propiedades
        self.propiedad1 = Propiedad.objects.create(
            portafolio=self.portafolio1,
            nombre_o_numero='Apto 1A',
            estado='DISPONIBLE'
        )
        self.propiedad2 = Propiedad.objects.create(
            portafolio=self.portafolio2,
            nombre_o_numero='Apto 2B',
            estado='DISPONIBLE'
        )
        
        # Create inquilinos
        self.inquilino1 = Inquilino.objects.create(
            nombre='Inquilino Uno',
            telefono='809-111-1111',
            correo='inquilino1@test.com',
            creado_por=self.user1
        )
        self.inquilino2 = Inquilino.objects.create(
            nombre='Inquilino Dos',
            telefono='809-222-2222',
            correo='inquilino2@test.com',
            creado_por=self.user2
        )
        
        # Create contratos
        self.contrato1 = Contrato.objects.create(
            propiedad=self.propiedad1,
            inquilino=self.inquilino1,
            fecha_inicio=date(2026, 1, 1),
            monto_renta=10000.00,
            dia_de_pago=5,
            activo=True
        )

        self.client = Client()

    def test_editar_inquilino_seguridad(self):
        # Login as user2 and try to edit user1's tenant
        self.client.login(username='propietario2', password='password123')
        url = reverse('editar_inquilino', args=[self.inquilino1.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404) # Should be forbidden/404 because inquilino1 belongs to user1

        # Login as user1 and edit successfully
        self.client.login(username='propietario1', password='password123')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        
        post_data = {
            'nombre': 'Inquilino Uno Modificado',
            'telefono': '809-999-9999',
            'correo': 'inquilino1_mod@test.com',
            'cedula_o_pasaporte': '001-0000000-0',
            'recibir_alertas_correo': True
        }
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 302) # Redirect to detail
        self.inquilino1.refresh_from_db()
        self.assertEqual(self.inquilino1.nombre, 'Inquilino Uno Modificado')
        self.assertEqual(self.inquilino1.telefono, '809-999-9999')

    def test_registrar_aumento_renta(self):
        self.client.login(username='propietario1', password='password123')
        url = reverse('registrar_aumento_renta', args=[self.contrato1.id])
        
        # Post increase
        post_data = {
            'nuevo_monto': '12500.00',
            'fecha_aumento': '2026-06-01'
        }
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 302) # Redirect to property detail
        
        # Verify contract rent updated
        self.contrato1.refresh_from_db()
        self.assertEqual(float(self.contrato1.monto_renta), 12500.00)
        
        # Verify history created
        aumentos = self.contrato1.aumentos.all()
        self.assertEqual(aumentos.count(), 1)
        aumento = aumentos.first()
        self.assertEqual(float(aumento.monto_anterior), 10000.00)
        self.assertEqual(float(aumento.nuevo_monto), 12500.00)
        self.assertEqual(aumento.fecha_aumento.strftime('%Y-%m-%d'), '2026-06-01')
        self.assertEqual(aumento.usuario, self.user1)
        
        # Verify AuditLog created
        logs = AuditLog.objects.filter(modulo='Contrato', accion='EDITAR')
        self.assertTrue(logs.exists())

    def test_marketplace_acceso_publico(self):
        # Create a public listing
        pub = PublicacionMarketplace.objects.create(
            propiedad=self.propiedad1,
            titulo="Espectacular Apto 1A",
            descripcion="Hermoso apartamento centrico",
            precio_renta=12000.00,
            telefono_contacto="+18095551234",
            creado_por=self.user1
        )
        
        # Test catalog access without logging in
        url_catalogo = reverse('marketplace_catalogo')
        response = self.client.get(url_catalogo)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Espectacular Apto 1A")
        
        # Test detail access without logging in
        url_detalle = reverse('marketplace_detalle', args=[pub.pk])
        response = self.client.get(url_detalle)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Espectacular Apto 1A")

    def test_marketplace_permisos_y_seguridad(self):
        # Ensure anonymous user cannot access creation view
        url_crear = reverse('crear_publicacion_marketplace', args=[self.propiedad1.id])
        response = self.client.get(url_crear)
        self.assertEqual(response.status_code, 302) # Redirect to login

        # Login as user2 (not authorized for propiedad1 which belongs to portafolio1 of user1)
        self.client.login(username='propietario2', password='password123')
        
        # Attempt to view creation page for user1's property
        response = self.client.get(url_crear)
        self.assertEqual(response.status_code, 403) # PermissionDenied

        # Try to post a creation request
        post_data = {
            'titulo': 'Apartamento Fraudulento',
            'descripcion': 'Intento de publicar sin permiso',
            'precio_renta': '15000.00',
            'telefono_contacto': '+18091111111'
        }
        response = self.client.post(url_crear, post_data)
        self.assertEqual(response.status_code, 403) # PermissionDenied

    def test_marketplace_vigencia_y_periodo_de_gracia(self):
        # 1. Active listing (<40 days old)
        pub = PublicacionMarketplace.objects.create(
            propiedad=self.propiedad1,
            titulo="Apto Activo",
            descripcion="Descripción",
            precio_renta=10000.00,
            telefono_contacto="+18090000000",
            creado_por=self.user1,
            fecha_activacion=timezone.now() - timedelta(days=10)
        )
        self.assertEqual(pub.estado_vigencia, 'ACTIVA')
        self.assertEqual(pub.dias_restantes, 35)
        self.assertTrue(pub.esta_visible)

        # 2. Near expiration (40-44 days old)
        pub.fecha_activacion = timezone.now() - timedelta(days=41)
        pub.save()
        self.assertEqual(pub.estado_vigencia, 'PROXIMA_A_VENCER')
        self.assertEqual(pub.dias_restantes, 4)
        self.assertTrue(pub.esta_visible)

        # 3. Expired / In Grace Period (45-49 days old)
        pub.fecha_activacion = timezone.now() - timedelta(days=47)
        pub.save()
        self.assertEqual(pub.estado_vigencia, 'VENCIDA')
        self.assertEqual(pub.dias_restantes, 0)
        self.assertFalse(pub.esta_visible)
        self.assertEqual(pub.dias_gracia_restantes, 3)

        # Public user should get a 404 when viewing an expired listing
        response = self.client.get(reverse('marketplace_detalle', args=[pub.pk]))
        self.assertEqual(response.status_code, 404)

        # Authorized owner can still previsualize it
        self.client.login(username='propietario1', password='password123')
        response = self.client.get(reverse('marketplace_detalle', args=[pub.pk]))
        self.assertEqual(response.status_code, 200)

    def test_marketplace_borrado_fisico_multimedia(self):
        # Create public listing
        pub = PublicacionMarketplace.objects.create(
            propiedad=self.propiedad1,
            titulo="Apto con Fotos",
            descripcion="Fotos de prueba",
            precio_renta=10000.00,
            telefono_contacto="+18095559999",
            creado_por=self.user1
        )
        
        # Mock simple image upload
        image_content = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82'
        uploaded_image = SimpleUploadedFile("test_prop_photo.png", image_content, content_type="image/png")
        
        img_instance = ImagenPublicacion.objects.create(
            publicacion=pub,
            imagen=uploaded_image
        )
        
        # Verify file physically exists on disk
        img_path = img_instance.imagen.path
        self.assertTrue(os.path.exists(img_path))
        
        # Delete listing and ensure file is physically deleted from disk
        pub.delete()
        self.assertFalse(os.path.exists(img_path))

    def test_marketplace_limpieza_automatica_50_dias(self):
        # Create listing older than 50 days
        pub = PublicacionMarketplace.objects.create(
            propiedad=self.propiedad1,
            titulo="Apto Abandonado",
            descripcion="Anuncio sin accion",
            precio_renta=10000.00,
            telefono_contacto="+18091234567",
            creado_por=self.user1,
            fecha_activacion=timezone.now() - timedelta(days=52)
        )
        
        # Mock image
        image_content = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82'
        uploaded_image = SimpleUploadedFile("abandoned_photo.png", image_content, content_type="image/png")
        img_instance = ImagenPublicacion.objects.create(
            publicacion=pub,
            imagen=uploaded_image
        )
        img_path = img_instance.imagen.path
        self.assertTrue(os.path.exists(img_path))
        
        # Trigger dynamic cleanup by querying public catalog view
        response = self.client.get(reverse('marketplace_catalogo'))
        self.assertEqual(response.status_code, 200)
        
        # Verify the listing record is completely purged from DB
        self.assertFalse(PublicacionMarketplace.objects.filter(pk=pub.pk).exists())
        # Verify the media file is physically deleted from disk
        self.assertFalse(os.path.exists(img_path))

