from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from datetime import date, timedelta
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
import os
from .models import Portafolio, Propiedad, Inquilino, Contrato, HistorialAumentoRenta, AuditLog, PlanSaaS, SuscripcionCliente, PublicacionMarketplace, ImagenPublicacion, PropietarioInmueble, GastoGeneralPropietario, LiquidacionPropietario, Factura, ReciboPago, MantenimientoUnidad, LiquidacionDepositoInquilino

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

    def test_propietario_inmueble_crud(self):
        self.client.login(username='propietario1', password='password123')
        
        # 1. Crear Propietario Inmueble
        post_data = {
            'nombre': 'Don Carlos Almonte',
            'cedula_o_rnc': '001-1234567-8',
            'telefono': '809-555-4321',
            'correo': 'carlos@almonte.com',
            'tipo_comision': 'PORCENTAJE',
            'porcentaje_comision': '10.00',
            'banco_nombre': 'Banco Popular',
            'numero_cuenta': '123456789',
            'activo': True
        }
        res = self.client.post(reverse('crear_propietario'), post_data)
        self.assertEqual(res.status_code, 302)
        
        prop_owner = PropietarioInmueble.objects.get(nombre='Don Carlos Almonte')
        self.assertEqual(prop_owner.portafolio, self.portafolio1)
        self.assertEqual(float(prop_owner.porcentaje_comision), 10.00)
        
        # 2. Asignar propietario a una propiedad existente
        self.propiedad1.propietario_inmueble = prop_owner
        self.propiedad1.save()
        self.assertEqual(self.propiedad1.propietario_inmueble, prop_owner)

    def test_calculo_liquidacion_propietario(self):
        self.client.login(username='propietario1', password='password123')
        
        # Crear Propietario con 10% de comisión
        owner = PropietarioInmueble.objects.create(
            portafolio=self.portafolio1,
            nombre='Doña Maria Lopez',
            tipo_comision='PORCENTAJE',
            porcentaje_comision=10.00
        )
        self.propiedad1.propietario_inmueble = owner
        self.propiedad1.save()
        
        # Simulamos cobro de factura de 20,000 en el mes actual
        hoy = date.today()
        factura = Factura.objects.create(
            contrato=self.contrato1,
            fecha_emision=hoy,
            fecha_vencimiento=hoy,
            monto_base=20000.00,
            concepto='Renta Prueba Liquidacion',
            estado='PAGADA'
        )
        ReciboPago.objects.create(
            factura=factura,
            fecha_pago=hoy,
            monto_pagado=20000.00,
            metodo_pago='TRANSFERENCIA'
        )
        
        # Registramos mantenimiento directo de $2,000
        MantenimientoUnidad.objects.create(
            propiedad=self.propiedad1,
            descripcion='Reparación Tubería',
            costo=2000.00,
            estado='COMPLETADO',
            fecha_reporte=hoy
        )
        
        # Registramos Gasto General de $1,000 (Gestión Legal)
        GastoGeneralPropietario.objects.create(
            portafolio=self.portafolio1,
            propietario_inmueble=owner,
            concepto='Honorarios Abogado Contrato',
            monto=1000.00,
            categoria='GESTION_LEGAL',
            fecha=hoy
        )
        
        # Consultamos el reporte de liquidación
        url = f"{reverse('reporte_propietario')}?propietario_id={owner.id}&mes={hoy.month}&anio={hoy.year}"
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        
        # Comprobamos cálculos:
        # Total Cobrado = 20,000
        # Comisión (10%) = 2,000
        # Gastos Propiedad = 2,000
        # Gastos Generales = 1,000
        # Total Deducciones = 5,000
        # Neto a Liquidar = 20,000 - 5,000 = 15,000
        self.assertEqual(float(res.context['total_ingresos']), 20000.00)
        self.assertEqual(float(res.context['monto_comision']), 2000.00)
        self.assertEqual(float(res.context['total_gastos_propiedades']), 2000.00)
        self.assertEqual(float(res.context['total_gastos_generales']), 1000.00)
        self.assertEqual(float(res.context['total_deducciones']), 5000.00)
        self.assertEqual(float(res.context['neto_a_liquidar']), 15000.00)
        
        # Procesamos la liquidación oficial
        liq_url = reverse('procesar_liquidacion_propietario', args=[owner.id])
        post_liq = {
            'mes': hoy.month,
            'anio': hoy.year,
            'fecha_pago': hoy.strftime('%Y-%m-%d'),
            'metodo_pago': 'TRANSFERENCIA',
            'referencia_transaccion': 'TXN-TEST-12345'
        }
        res_post = self.client.post(liq_url, post_liq)
        self.assertEqual(res_post.status_code, 302)
        
        liq = LiquidacionPropietario.objects.get(propietario_inmueble=owner, periodo_mes=hoy.month, periodo_anio=hoy.year)
        self.assertEqual(float(liq.monto_neto_pagado), 15000.00)
        self.assertEqual(liq.estado, 'PAGADO')

    def test_finalizar_contrato_y_liquidacion_deposito(self):
        self.client.login(username='propietario1', password='password123')
        
        # Asignamos depósito de 20,000 al contrato 1
        self.contrato1.monto_deposito = 20000.00
        self.contrato1.save()
        
        url_get = reverse('finalizar_contrato', args=[self.contrato1.id])
        res_get = self.client.get(url_get)
        self.assertEqual(res_get.status_code, 200)
        
        # Procesamos la finalización con $3,000 de deducción por daños
        post_data = {
            'monto_deduccion_facturas': '0.00',
            'monto_deduccion_danos': '3000.00',
            'fecha_liquidacion': date.today().strftime('%Y-%m-%d'),
            'metodo_devolucion': 'TRANSFERENCIA',
            'referencia_pago': 'TXN-FINIQUITO-999',
            'detalles_danos': 'Pintura y cambio de cerraduras'
        }
        res_post = self.client.post(url_get, post_data)
        self.assertEqual(res_post.status_code, 302) # Redirige al acta imprimible
        
        # Verificamos estado del contrato y propiedad
        self.contrato1.refresh_from_db()
        self.assertFalse(self.contrato1.activo)
        self.assertEqual(self.propiedad1.estado, 'DISPONIBLE')
        
        # Verificamos registro de liquidación de depósito
        liq = LiquidacionDepositoInquilino.objects.get(contrato=self.contrato1)
        self.assertEqual(float(liq.monto_deposito_original), 20000.00)
        self.assertEqual(float(liq.monto_deduccion_danos), 3000.00)
        self.assertEqual(float(liq.monto_neto_devuelto), 17000.00) # 20,000 - 3,000 = 17,000
        self.assertEqual(liq.estado, 'DEVUELTO')

    def test_historial_precios_y_mapa_propiedades(self):
        # 1. Asignar coordenadas y precio sugerido a propiedad1
        self.propiedad1.precio_alquiler_sugerido = 15000.00
        self.propiedad1.latitud = 18.486058
        self.propiedad1.longitud = -69.931211
        self.propiedad1.save()
        
        # 2. Registrar cambio de precio mediante la vista
        self.client.login(username='propietario1', password='password123')
        url_cambio = reverse('registrar_cambio_precio_propiedad', args=[self.propiedad1.id])
        post_data = {
            'nuevo_precio': '17500.00',
            'motivo': 'AJUSTE_MERCADO',
            'fecha_cambio': date.today().strftime('%Y-%m-%d'),
            'notas': 'Aumento general del sector'
        }
        response = self.client.post(url_cambio, post_data)
        self.assertEqual(response.status_code, 302)
        
        # Verificamos actualización en Propiedad y en HistorialPrecioPropiedad
        self.propiedad1.refresh_from_db()
        self.assertEqual(float(self.propiedad1.precio_alquiler_sugerido), 17500.00)
        self.assertEqual(self.propiedad1.historial_precios.count(), 1)
        hist = self.propiedad1.historial_precios.first()
        self.assertEqual(float(hist.precio_anterior), 15000.00)
        self.assertEqual(float(hist.nuevo_precio), 17500.00)
        
        # 3. Probar vista mapa global
        url_mapa = reverse('mapa_propiedades_global')
        res_mapa = self.client.get(url_mapa)
        self.assertEqual(res_mapa.status_code, 200)
        self.assertIn('Apto 1A', res_mapa.content.decode('utf-8'))

    def test_respaldos_y_papelera_reciclaje(self):
        self.client.login(username='propietario1', password='password123')
        
        # 1. Probar vista panel respaldos
        res_respaldos = self.client.get(reverse('respaldos_exportacion'))
        self.assertEqual(res_respaldos.status_code, 200)
        
        # 2. Probar exportar datos en ZIP/CSV
        res_export_datos = self.client.get(reverse('exportar_datos_csv_zip'))
        self.assertEqual(res_export_datos.status_code, 200)
        self.assertEqual(res_export_datos['Content-Type'], 'application/zip')
        
        # 3. Probar eliminar propiedad y recuperarla desde papelera
        self.propiedad1.is_deleted = True
        self.propiedad1.save()
        
        res_papelera = self.client.get(reverse('papelera_reciclaje'))
        self.assertEqual(res_papelera.status_code, 200)
        self.assertIn('Apto 1A', res_papelera.content.decode('utf-8'))
        
        # Restaurar
        url_restaurar = reverse('restaurar_propiedad', args=[self.propiedad1.id])
        res_restaurar = self.client.post(url_restaurar)
        self.assertEqual(res_restaurar.status_code, 302)
        
        self.propiedad1.refresh_from_db()
        self.assertFalse(self.propiedad1.is_deleted)

