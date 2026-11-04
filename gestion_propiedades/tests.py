from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from datetime import date, timedelta
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
import os
from .models import Portafolio, Propiedad, Inquilino, Contrato, HistorialAumentoRenta, AuditLog, PlanSaaS, SuscripcionCliente, FacturaSaaS, PublicacionMarketplace, ImagenPublicacion, PropietarioInmueble, GastoGeneralPropietario, LiquidacionPropietario, Factura, ReciboPago, MantenimientoUnidad, LiquidacionDepositoInquilino, CargoAdicionalContrato, DetalleFacturaServicio, CargoMora
from decimal import Decimal

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

    def test_nuevas_funcionalidades_garante_y_custodia(self):
        from .models import SolicitudAlquiler
        
        # 1. Probar custodia de depósito en contrato
        self.contrato1.custodia_deposito = 'BANCO_CONSIGNACION'
        self.contrato1.detalles_custodia_deposito = 'Consignación No. 998877 Banco Agrícola'
        self.contrato1.save()
        self.assertEqual(self.contrato1.custodia_deposito, 'BANCO_CONSIGNACION')

        # 2. Crear solicitud con fiador y devolverla para corrección
        solicitud = SolicitudAlquiler.objects.create(
            propiedad=self.propiedad1,
            nombre_completo='Prospecto Prueba',
            cedula='402-0000000-1',
            tiene_fiador=True,
            fiador_nombre='Garante Prueba',
            fiador_cedula='001-0000000-2'
        )
        self.client.login(username='propietario1', password='password123')
        
        url_devolver = reverse('devolver_solicitud_alquiler', args=[solicitud.id])
        res_devolver = self.client.post(url_devolver, {'motivo_devolucion': 'Fiador no califica, favor cambiar.'})
        self.assertEqual(res_devolver.status_code, 302)
        
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, 'DEVUELTA_PARA_CORRECCION')
        self.assertEqual(solicitud.motivo_devolucion, 'Fiador no califica, favor cambiar.')

        # 3. Probar impresión de Estado de Situación de Propiedades
        prop_owner = PropietarioInmueble.objects.create(
            portafolio=self.portafolio1,
            nombre='Propietario Test',
            cedula_o_rnc='402-1234567-8'
        )
        self.propiedad1.propietario_inmueble = prop_owner
        self.propiedad1.save()
        
        url_situacion_pdf = reverse('imprimir_estado_situacion_propietario', args=[prop_owner.id])
        res_situacion_pdf = self.client.get(url_situacion_pdf)
        self.assertEqual(res_situacion_pdf.status_code, 200)
        self.assertIn('ESTADO DE SITUACIÓN DE INMUEBLES', res_situacion_pdf.content.decode('utf-8'))

    def test_superuser_cambiar_password(self):
        # 1. Non-superuser cannot change user2 password
        self.client.login(username='propietario1', password='password123')
        url = reverse('cambiar_password', args=[self.user2.id])
        res_denied = self.client.get(url)
        self.assertEqual(res_denied.status_code, 302)

        # 2. Superuser can access and change user2 password
        superuser = User.objects.create_superuser(username='superadmin', password='adminpassword', email='admin@test.com')
        SuscripcionCliente.objects.create(usuario=superuser, plan_saas=self.plan, estado='ACTIVA')
        
        self.client.login(username='superadmin', password='adminpassword')
        res_get = self.client.get(url)
        self.assertEqual(res_get.status_code, 200)

        res_post = self.client.post(url, {'password': 'newpassword123'})
        self.assertEqual(res_post.status_code, 302)
        self.assertRedirects(res_post, reverse('saas_master_control'))

        # Check password changed
        self.client.logout()
        login_success = self.client.login(username='propietario2', password='newpassword123')
        self.assertTrue(login_success)

    def test_recibo_ingresos_y_recordatorio_vencimiento_contrato(self):
        # 1. Probar que el recibo impreso diga "RECIBO DE INGRESOS"
        factura = Factura.objects.create(
            contrato=self.contrato1,
            fecha_emision=date.today(),
            fecha_vencimiento=date.today(),
            monto_base=10000.00,
            estado='PAGADA',
            concepto='Alquiler del mes'
        )
        recibo = ReciboPago.objects.create(
            factura=factura,
            monto_pagado=10000.00,
            fecha_pago=date.today(),
            registrado_por=self.user1
        )
        self.client.login(username='propietario1', password='password123')
        url_recibo = reverse('imprimir_recibo', args=[recibo.id])
        res_recibo = self.client.get(url_recibo)
        self.assertEqual(res_recibo.status_code, 200)
        self.assertIn('RECIBO DE INGRESOS', res_recibo.content.decode('utf-8'))

        # 2. Probar recordatorio de vencimiento de contrato en el Dashboard
        self.contrato1.fecha_fin = date.today() + timedelta(days=20)
        self.contrato1.recordatorio_vencimiento_meses = 1
        self.contrato1.save()

        res_dashboard = self.client.get(reverse('dashboard'))
        self.assertEqual(res_dashboard.status_code, 200)
        self.assertIn('Recordatorio de Vencimiento de Contratos', res_dashboard.content.decode('utf-8'))
        self.assertIn('Vence en 20 días', res_dashboard.content.decode('utf-8'))

    def test_reporte_movimientos_detallados_excel_y_correo(self):
        self.client.login(username='propietario1', password='password123')
        
        # 1. Probar carga HTML de reporte movimientos detallados
        url_reporte = reverse('reporte_movimientos_detallados')
        res_rep = self.client.get(url_reporte)
        self.assertEqual(res_rep.status_code, 200)
        self.assertIn('Reporte Detallado de Ingresos y Gastos', res_rep.content.decode('utf-8'))

        # 2. Probar descarga de Excel (.xlsx)
        url_excel = reverse('exportar_movimientos_excel')
        res_excel = self.client.get(url_excel)
        self.assertEqual(res_excel.status_code, 200)
        self.assertEqual(res_excel['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

        # 3. Probar envío de reporte por correo
        url_email = reverse('enviar_movimientos_correo')
        res_email = self.client.post(url_email, {'email_destino': 'contador@test.com'})
        self.assertEqual(res_email.status_code, 302)

    def test_reporte_estado_propiedades_propietario(self):
        self.client.login(username='propietario1', password='password123')
        
        # 1. Probar vista HTML del reporte
        url_reporte = reverse('reporte_estado_propiedades_propietario')
        res = self.client.get(url_reporte)
        self.assertEqual(res.status_code, 200)
        self.assertIn('Estado Mensual de Propiedades por Propietario', res.content.decode('utf-8'))

        # 2. Probar exportación a Excel (.xlsx)
        url_excel = reverse('exportar_estado_propiedades_excel')
        res_excel = self.client.get(url_excel)
        self.assertEqual(res_excel.status_code, 200)
        self.assertEqual(res_excel['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

        # 3. Probar vista de impresión PDF
        url_print = reverse('imprimir_estado_propiedades_propietario')
        res_print = self.client.get(url_print)
        self.assertEqual(res_print.status_code, 200)
        self.assertIn('Estado Mensual de Inmuebles por Propietario', res_print.content.decode('utf-8'))

    def test_cargos_adicionales_contrato(self):
        # 1. Agregar cargos adicionales recurrentes
        cargo1 = CargoAdicionalContrato.objects.create(
            contrato=self.contrato1,
            categoria='MANTENIMIENTO',
            monto=Decimal('2500.00'),
            activo=True
        )
        cargo2 = CargoAdicionalContrato.objects.create(
            contrato=self.contrato1,
            categoria='AGUA',
            monto=Decimal('300.00'),
            activo=True
        )
        self.assertEqual(self.contrato1.total_cargos_adicionales, Decimal('2800.00'))
        self.assertEqual(self.contrato1.total_cuota_mensual, Decimal('12800.00'))
        self.assertEqual(cargo1.nombre_mostrar, 'Mantenimiento')

    def test_crear_factura_manual_view(self):
        # 1. Non-superuser debe ser rechazado
        self.client.login(username='propietario1', password='password123')
        url = reverse('crear_factura_manual')
        res_denied = self.client.get(url + f'?contrato_id={self.contrato1.id}')
        self.assertEqual(res_denied.status_code, 302) # Redirige con mensaje de error
        self.assertRedirects(res_denied, reverse('lista_facturas_global'))

        # 2. Superuser sí tiene acceso para onboarding y facturación extraordinaria
        self.user1.is_superuser = True
        self.user1.save()

        res_get = self.client.get(url + f'?contrato_id={self.contrato1.id}')
        self.assertEqual(res_get.status_code, 200)
        self.assertIn('Generar Factura Manual / Días Anteriores', res_get.content.decode('utf-8'))

        # Probar filtro por portafolio para Superusuario
        res_filtro = self.client.get(url + f'?portafolio_id={self.portafolio1.id}')
        self.assertEqual(res_filtro.status_code, 200)
        self.assertIn('portafolios', res_filtro.context)
        self.assertIn('Filtrar por Portafolio', res_filtro.content.decode('utf-8'))

        # Probar POST creando factura manual para días anteriores con concepto personalizado
        post_data = {
            'contrato': self.contrato1.id,
            'fecha_emision': '2026-10-15',
            'fecha_vencimiento': '2026-10-25',
            'monto_renta': '5000.00',
            'concepto': 'Días anteriores del 15 al 30 de Octubre 2026',
            'extra_categoria[]': ['MANTENIMIENTO', 'AGUA'],
            'extra_concepto[]': ['Mantenimiento proporcional', 'Cuota de agua'],
            'extra_monto[]': ['1000.00', '200.00']
        }
        res_post = self.client.post(url, post_data)
        self.assertEqual(res_post.status_code, 302)

        # Verificar factura creada
        factura = Factura.objects.filter(contrato=self.contrato1, concepto='Días anteriores del 15 al 30 de Octubre 2026').first()
        self.assertIsNotNone(factura)
        self.assertEqual(factura.monto_renta, Decimal('5000.00'))
        self.assertEqual(factura.monto_servicios, Decimal('1200.00'))
        self.assertEqual(factura.monto_base, Decimal('6200.00'))
        self.assertEqual(factura.detalles_servicios.count(), 2)
        self.assertEqual(factura.estado, 'ATRASADA') # Porque vencimiento (2026-10-25) es anterior a hoy

        # Probar POST creando factura manual CON MORA aplicada
        post_data_mora = {
            'contrato': self.contrato1.id,
            'fecha_emision': '2026-09-01',
            'fecha_vencimiento': '2026-09-10',
            'monto_renta': '10000.00',
            'concepto': 'Renta Septiembre con Mora Manual',
            'aplicar_mora': 'on',
            'monto_mora': '1000.00'
        }
        res_post_mora = self.client.post(url, post_data_mora)
        self.assertEqual(res_post_mora.status_code, 302)

        factura_mora = Factura.objects.filter(contrato=self.contrato1, concepto='Renta Septiembre con Mora Manual').first()
        self.assertIsNotNone(factura_mora)
        self.assertEqual(factura_mora.monto_renta, Decimal('10000.00'))
        self.assertEqual(factura_mora.total_mora, Decimal('1000.00'))
        self.assertEqual(factura_mora.monto_total_con_mora, Decimal('11000.00'))
        self.assertEqual(factura_mora.moras.count(), 1)
        self.assertEqual(factura_mora.estado, 'ATRASADA')

        # Restaurar usuario
        self.user1.is_superuser = False
        self.user1.save()

    def test_gestionar_servicios_contrato_view(self):
        self.client.login(username='propietario1', password='password123')
        url = reverse('gestionar_servicios_contrato', args=[self.contrato1.id])

        # Probar GET
        res_get = self.client.get(url)
        self.assertEqual(res_get.status_code, 200)
        self.assertIn('Servicios Adicionales Recurrentes', res_get.content.decode('utf-8'))

        # Probar POST configurando Agua (500) y Luz de Bomba (350)
        post_data = {
            'cargo_categoria[]': ['AGUA', 'LUZ_BOMBA'],
            'cargo_concepto[]': ['Agua potable residencial', 'Bomba sumergible'],
            'cargo_monto[]': ['500.00', '350.00']
        }
        res_post = self.client.post(url, post_data)
        self.assertEqual(res_post.status_code, 302)

        self.contrato1.refresh_from_db()
        self.assertEqual(self.contrato1.cargos_adicionales.count(), 2)
        self.assertEqual(self.contrato1.total_cargos_adicionales, Decimal('850.00'))
        self.assertEqual(self.contrato1.total_cuota_mensual, Decimal('10850.00'))

    def test_orden_abono_mora_servicios_alquiler(self):
        # Crear factura con: Alquiler 10,000, Servicios 2,000, Mora 1,000 (Total deuda: 13,000)
        factura = Factura.objects.create(
            contrato=self.contrato1,
            fecha_emision=date(2026, 10, 1),
            fecha_vencimiento=date(2026, 10, 5),
            monto_base=Decimal('12000.00'),
            monto_renta=Decimal('10000.00'),
            monto_servicios=Decimal('2000.00'),
            concepto='Factura Octubre 2026',
            estado='ATRASADA'
        )
        CargoMora.objects.create(
            factura=factura,
            monto=Decimal('1000.00'),
            mes_aplicado=10,
            anio_aplicado=2026
        )

        self.assertEqual(factura.monto_total_con_mora, Decimal('13000.00'))
        self.assertEqual(factura.saldo_mora_pendiente, Decimal('1000.00'))
        self.assertEqual(factura.saldo_servicios_pendiente, Decimal('2000.00'))
        self.assertEqual(factura.saldo_renta_pendiente, Decimal('10000.00'))

        # ABONO 1: Inquilino abona RD$ 1,500
        # Orden de imputación: 1. Mora (1,000), 2. Servicios (500), 3. Alquiler (0)
        recibo1 = ReciboPago.objects.create(
            factura=factura,
            fecha_pago=date(2026, 10, 10),
            monto_pagado=Decimal('1500.00'),
            registrado_por=self.user1
        )
        self.assertEqual(recibo1.monto_a_mora, Decimal('1000.00'))
        self.assertEqual(recibo1.monto_a_servicios, Decimal('500.00'))
        self.assertEqual(recibo1.monto_a_renta, Decimal('0.00'))

        # Verificación de saldos tras Abono 1
        self.assertEqual(factura.saldo_mora_pendiente, Decimal('0.00'))
        self.assertEqual(factura.saldo_servicios_pendiente, Decimal('1500.00'))
        self.assertEqual(factura.saldo_renta_pendiente, Decimal('10000.00'))
        self.assertEqual(factura.saldo_pendiente, Decimal('11500.00'))
        self.assertFalse(factura.renta_esta_saldada)

        # ABONO 2: Inquilino abona RD$ 2,000
        # Orden de imputación: 1. Mora (0 porque ya está en 0), 2. Servicios (1,500), 3. Alquiler (500)
        recibo2 = ReciboPago.objects.create(
            factura=factura,
            fecha_pago=date(2026, 10, 15),
            monto_pagado=Decimal('2000.00'),
            registrado_por=self.user1
        )
        self.assertEqual(recibo2.monto_a_mora, Decimal('0.00'))
        self.assertEqual(recibo2.monto_a_servicios, Decimal('1500.00'))
        self.assertEqual(recibo2.monto_a_renta, Decimal('500.00'))

        # Verificación de saldos tras Abono 2
        self.assertEqual(factura.saldo_mora_pendiente, Decimal('0.00'))
        self.assertEqual(factura.saldo_servicios_pendiente, Decimal('0.00'))
        self.assertEqual(factura.saldo_renta_pendiente, Decimal('9500.00'))
        self.assertEqual(factura.saldo_pendiente, Decimal('9500.00'))
        self.assertFalse(factura.renta_esta_saldada)

        # PAGO FINAL: Inquilino salda los RD$ 9,500 restantes
        recibo3 = ReciboPago.objects.create(
            factura=factura,
            fecha_pago=date(2026, 10, 20),
            monto_pagado=Decimal('9500.00'),
            registrado_por=self.user1
        )
        self.assertEqual(recibo3.monto_a_mora, Decimal('0.00'))
        self.assertEqual(recibo3.monto_a_servicios, Decimal('0.00'))
        self.assertEqual(recibo3.monto_a_renta, Decimal('9500.00'))

        self.assertEqual(factura.saldo_renta_pendiente, Decimal('0.00'))
        self.assertEqual(factura.saldo_pendiente, Decimal('0.00'))
        self.assertTrue(factura.renta_esta_saldada)

    def test_comision_abogados_excluye_servicios_y_mora(self):
        # Crear propietario con 10% de comisión
        propietario = PropietarioInmueble.objects.create(
            portafolio=self.portafolio1,
            nombre='Propietario Don Basora',
            porcentaje_comision=Decimal('10.00'),
            tipo_comision='PORCENTAJE'
        )
        self.propiedad1.propietario_inmueble = propietario
        self.propiedad1.save()

        # Factura: Alquiler 10,000, Servicios 3,000
        factura = Factura.objects.create(
            contrato=self.contrato1,
            fecha_emision=date(2026, 11, 1),
            fecha_vencimiento=date(2026, 11, 5),
            monto_base=Decimal('13000.00'),
            monto_renta=Decimal('10000.00'),
            monto_servicios=Decimal('3000.00'),
            concepto='Renta y Mantenimiento Noviembre 2026',
            estado='PENDIENTE'
        )

        # Cobro completo de los 13,000
        recibo = ReciboPago.objects.create(
            factura=factura,
            fecha_pago=date(2026, 11, 2),
            monto_pagado=Decimal('13000.00'),
            registrado_por=self.user1
        )
        self.assertEqual(recibo.monto_a_servicios, Decimal('3000.00'))
        self.assertEqual(recibo.monto_a_renta, Decimal('10000.00'))

        self.client.login(username='propietario1', password='password123')
        # Procesar liquidación del propietario
        url_liq = reverse('procesar_liquidacion_propietario', args=[propietario.id])
        res = self.client.post(url_liq, {
            'mes': 11,
            'anio': 2026,
            'metodo_pago': 'TRANSFERENCIA'
        })
        self.assertEqual(res.status_code, 302)

        liquidacion = LiquidacionPropietario.objects.get(
            propietario_inmueble=propietario,
            periodo_mes=11,
            periodo_anio=2026
        )
        # Total cobrado es 13,000
        self.assertEqual(liquidacion.monto_rentas_cobradas, Decimal('13000.00'))
        # Comisión del 10% es SOLO sobre los 10,000 de renta = 1,000 (NO sobre 13,000 que daría 1,300)
        self.assertEqual(liquidacion.monto_comision, Decimal('1000.00'))
        # Neto pagado al propietario: 13,000 - 1,000 = 12,000
        self.assertEqual(liquidacion.monto_neto_pagado, Decimal('12000.00'))

    def test_mora_continua_calculandose_hasta_saldar_alquiler(self):
        from django.core.management import call_command
        # Factura vencida donde inquilino solo pagó servicios pero debe el alquiler
        factura = Factura.objects.create(
            contrato=self.contrato1,
            fecha_emision=date.today() - timedelta(days=40),
            fecha_vencimiento=date.today() - timedelta(days=20),
            monto_base=Decimal('12000.00'),
            monto_renta=Decimal('10000.00'),
            monto_servicios=Decimal('2000.00'),
            concepto='Factura Vencida',
            estado='PENDIENTE'
        )
        self.contrato1.porcentaje_mora = Decimal('10.00')
        self.contrato1.save()

        # Inquilino abonó 2,000 (cubrió los servicios, pero alquiler sigue debiéndose: 10,000)
        ReciboPago.objects.create(
            factura=factura,
            fecha_pago=date.today() - timedelta(days=10),
            monto_pagado=Decimal('2000.00'),
            registrado_por=self.user1
        )
        self.assertEqual(factura.saldo_servicios_pendiente, Decimal('0.00'))
        self.assertEqual(factura.saldo_renta_pendiente, Decimal('10000.00'))

        # Ejecutamos cron de facturación diaria
        call_command('facturar_saas_diario')

        factura.refresh_from_db()
        self.assertEqual(factura.estado, 'ATRASADA')
        # Debe haberse generado mora sobre los 10,000 de alquiler pendiente (10% = 1,000)
        mora = CargoMora.objects.filter(factura=factura, mes_aplicado=date.today().month, anio_aplicado=date.today().year).first()
        self.assertIsNotNone(mora)
        self.assertEqual(mora.monto, Decimal('1000.00'))

    def test_liquidacion_con_comprobante_adjunto_y_whatsapp(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        # Propietario en portafolio 1
        prop_owner = PropietarioInmueble.objects.create(
            portafolio=self.portafolio1,
            nombre='Propietario Don Basora',
            telefono='809-555-1234',
            banco_nombre='Banco Popular Dominicano',
            tipo_cuenta='Corriente',
            numero_cuenta='789456123'
        )
        self.propiedad1.propietario_inmueble = prop_owner
        self.propiedad1.save()

        self.client.login(username='propietario1', password='password123')
        url = reverse('procesar_liquidacion_propietario', args=[prop_owner.id])

        pdf_dummy = SimpleUploadedFile("comprobante_transferencia.pdf", b"%PDF-1.4 test dummy content", content_type="application/pdf")
        post_data = {
            'mes': 11,
            'anio': 2026,
            'fecha_pago': '2026-11-04',
            'metodo_pago': 'TRANSFERENCIA',
            'referencia_transaccion': 'TXN-BANK-9988',
            'notas': 'Transferencia vía ACH Banco Popular',
            'comprobante_pago': pdf_dummy
        }
        res = self.client.post(url, post_data)
        self.assertEqual(res.status_code, 302)

        liquidacion = LiquidacionPropietario.objects.filter(propietario_inmueble=prop_owner, periodo_mes=11, periodo_anio=2026).first()
        self.assertIsNotNone(liquidacion)
        self.assertEqual(liquidacion.referencia_transaccion, 'TXN-BANK-9988')
        self.assertTrue(bool(liquidacion.comprobante_pago))
        self.assertIn('comprobante_transferencia', liquidacion.comprobante_pago.name)

        # Probar que la vista reporte_propietario genera el enlace de WhatsApp
        url_rep = reverse('reporte_propietario') + f'?propietario_id={prop_owner.id}&mes=11&anio=2026'
        res_rep = self.client.get(url_rep)
        self.assertEqual(res_rep.status_code, 200)
        self.assertIn('whatsapp_liquidacion_url', res_rep.context)
        self.assertIn('8095551234', res_rep.context['whatsapp_liquidacion_url'])
        self.assertIn('Avisar por WhatsApp', res_rep.content.decode('utf-8'))

    def test_emitir_factura_saas_cliente_y_cobro_adelantado(self):
        # 1. Crear nuevo cliente B2B con suscripción activa pero fecha_proximo_pago a futuro (+60 días)
        cliente_nuevo = User.objects.create_user(username='cliente_b2b_test', email='b2b@test.com', password='password123')
        sub = SuscripcionCliente.objects.create(
            usuario=cliente_nuevo,
            plan_saas=self.plan,
            estado='ACTIVA',
            fecha_proximo_pago=date.today() + timedelta(days=60)
        )
        # Portafolio con 1 propiedad
        p = Portafolio.objects.create(nombre='Portafolio B2B', propietario=cliente_nuevo)
        Propiedad.objects.create(portafolio=p, nombre_o_numero='Apto B2B-1')

        # 2. Superadmin emite factura SaaS directa con 1 clic
        self.user1.is_superuser = True
        self.user1.save()
        self.client.login(username='propietario1', password='password123')

        url_emitir = reverse('emitir_factura_saas_cliente', args=[cliente_nuevo.id])
        res = self.client.post(url_emitir)
        self.assertEqual(res.status_code, 302)
        self.assertRedirects(res, reverse('saas_facturacion'))

        # Verificar que se creó la FacturaSaaS por adelantado
        fs = FacturaSaaS.objects.filter(usuario=cliente_nuevo).first()
        self.assertIsNotNone(fs)
        self.assertEqual(fs.estado, 'PENDIENTE')
        self.assertEqual(fs.monto_total, Decimal('10.00')) # Precio mensual del plan

        # Marcar la factura SaaS como PAGADA
        url_pagar = reverse('marcar_factura_saas_pagada', args=[fs.id])
        res_pagar = self.client.post(url_pagar)
        self.assertEqual(res_pagar.status_code, 302)
        fs.refresh_from_db()
        self.assertEqual(fs.estado, 'PAGADA')

        # Restaurar usuario
        self.user1.is_superuser = False
        self.user1.save()

    def test_formato_recibo_ingresos_sin_mora_y_con_mora(self):
        self.client.login(username='propietario1', password='password123')

        # Configurar portafolio con formato RANGO_FECHAS
        self.portafolio1.formato_concepto_factura = 'RANGO_FECHAS'
        self.portafolio1.save()

        # Asignar propietario del inmueble
        propietario_inm = PropietarioInmueble.objects.create(
            portafolio=self.portafolio1,
            nombre='GESTORIA TAVERAS Y ASOCIADOS S R L'
        )
        self.propiedad1.propietario_inmueble = propietario_inm
        self.propiedad1.save()

        # 1. Factura y recibo SIN mora (Pago completo)
        factura_sin_mora = Factura.objects.create(
            contrato=self.contrato1,
            fecha_emision=date.today(),
            fecha_vencimiento=date.today(),
            monto_base=Decimal('7500.00'),
            monto_renta=Decimal('7500.00'),
            monto_servicios=Decimal('0.00'),
            estado='PAGADA',
            concepto='PAGO DESDE EL 3 DE OCTUBRE DEL 2026 HASTA EL 3 DE NOVIEMBRE DEL 2026'
        )
        recibo_sin_mora = ReciboPago.objects.create(
            factura=factura_sin_mora,
            monto_pagado=Decimal('7500.00'),
            fecha_pago=date.today(),
            registrado_por=self.user1
        )
        recibo_sin_mora.save()

        url_recibo = reverse('imprimir_recibo', args=[recibo_sin_mora.id])
        res = self.client.get(url_recibo)
        self.assertEqual(res.status_code, 200)
        html = res.content.decode('utf-8')

        # Verificaciones para recibo SIN mora y formato rango de fechas:
        self.assertNotIn('Mes de Cobertura:', html)
        self.assertIn('Propietario:', html)
        self.assertIn('GESTORIA TAVERAS Y ASOCIADOS S R L', html)
        self.assertNotIn('(con moras)', html)
        self.assertIn('Total Cuota del Período:', html)
        self.assertIn('Monto Total Recibido:', html)
        self.assertNotIn('Descuento a Alquiler', html)
        self.assertNotIn('Aplicación de este Abono', html)

        # 2. Factura y recibo CON mora
        factura_con_mora = Factura.objects.create(
            contrato=self.contrato1,
            fecha_emision=date.today(),
            fecha_vencimiento=date.today(),
            monto_base=Decimal('7500.00'),
            monto_renta=Decimal('7500.00'),
            monto_servicios=Decimal('0.00'),
            estado='PAGADA',
            concepto='PAGO DESDE EL 3 DE NOVIEMBRE DEL 2026 HASTA EL 3 DE DICIEMBRE DEL 2026'
        )
        CargoMora.objects.create(
            factura=factura_con_mora,
            monto=Decimal('750.00'),
            mes_aplicado=11,
            anio_aplicado=2026
        )
        recibo_con_mora = ReciboPago.objects.create(
            factura=factura_con_mora,
            monto_pagado=Decimal('8250.00'),
            fecha_pago=date.today(),
            registrado_por=self.user1
        )
        recibo_con_mora.save()

        url_recibo_mora = reverse('imprimir_recibo', args=[recibo_con_mora.id])
        res_mora = self.client.get(url_recibo_mora)
        self.assertEqual(res_mora.status_code, 200)
        html_mora = res_mora.content.decode('utf-8')

        # Verificaciones para recibo CON mora:
        self.assertIn('Cargo por Mora:', html_mora)
        self.assertIn('Total Cuota del Período (con mora):', html_mora)
        self.assertIn('Pago a Mora:', html_mora)
        self.assertIn('Pago a Alquiler:', html_mora)

    def test_editar_portafolio_marca_blanca_con_logo(self):
        self.client.login(username='propietario1', password='password123')
        url = reverse('editar_portafolio')
        
        # Probar GET
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertIn('Configuración de Marca Blanca', res.content.decode('utf-8'))

        # Probar POST con imagen
        from io import BytesIO
        from PIL import Image
        img_io = BytesIO()
        image = Image.new('RGB', (100, 100), color='blue')
        image.save(img_io, format='JPEG')
        img_io.seek(0)
        
        logo = SimpleUploadedFile('test_logo.jpg', img_io.read(), content_type='image/jpeg')
        post_data = {
            'portafolio_id': self.portafolio1.id,
            'nombre': 'Portafolio Marca Blanca Test',
            'eslogan': 'El mejor servicio inmobiliario',
            'formato_impresion': 'A4',
            'formato_concepto_factura': 'RANGO_FECHAS',
            'config_meses_deposito': 1,
            'config_meses_adelanto': 1,
            'logo_empresa': logo
        }
        res_post = self.client.post(url, post_data)
        self.assertEqual(res_post.status_code, 302)
        
        self.portafolio1.refresh_from_db()
        self.assertEqual(self.portafolio1.nombre, 'Portafolio Marca Blanca Test')

    def test_quitar_mora_factura_admin_y_superadmin(self):
        # 1. Crear factura con mora
        factura = Factura.objects.create(
            contrato=self.contrato1,
            fecha_emision=date.today() - timedelta(days=20),
            fecha_vencimiento=date.today() - timedelta(days=10),
            monto_base=Decimal('10000.00'),
            monto_renta=Decimal('10000.00'),
            estado='ATRASADA',
            concepto='Alquiler Noviembre'
        )
        CargoMora.objects.create(
            factura=factura,
            monto=Decimal('1000.00'),
            mes_aplicado=date.today().month,
            anio_aplicado=date.today().year
        )
        self.assertEqual(factura.total_mora, Decimal('1000.00'))
        self.assertEqual(factura.monto_total_con_mora, Decimal('11000.00'))

        # 2. Intentar quitar mora con usuario no autorizado
        User.objects.create_user(username='ajeno', password='password123')
        self.client.login(username='ajeno', password='password123')
        url_quitar = reverse('quitar_mora_factura', args=[factura.id])
        res_ajeno = self.client.post(url_quitar)
        self.assertEqual(res_ajeno.status_code, 302)
        factura.refresh_from_db()
        self.assertEqual(factura.total_mora, Decimal('1000.00'))

        # 3. Quitar mora como Administrador del Portafolio
        self.client.login(username='propietario1', password='password123')
        res_admin = self.client.post(url_quitar)
        self.assertEqual(res_admin.status_code, 302)
        factura.refresh_from_db()
        self.assertTrue(factura.mora_exonerada)
        self.assertEqual(factura.total_mora, Decimal('0.00'))
        self.assertEqual(factura.moras.count(), 0)
        self.assertEqual(factura.monto_total_con_mora, Decimal('10000.00'))

        # Verificar auditoría
        audit = AuditLog.objects.filter(modulo='Factura', descripcion__icontains='Mora condonada').first()
        self.assertIsNotNone(audit)

    def test_pago_anticipado_con_servicios_recurrentes_y_concepto_limpio(self):
        # 1. Configurar servicio recurrente en el contrato
        CargoAdicionalContrato.objects.create(
            contrato=self.contrato1,
            categoria='BASURA',
            concepto_personalizado='Basura y Mantenimiento',
            monto=Decimal('750.00'),
            activo=True
        )

        self.client.login(username='propietario1', password='password123')
        url_anticipado = reverse('registrar_pago_anticipado', args=[self.contrato1.id])
        
        # 2. Ver pantalla de adelanto (GET)
        res_get = self.client.get(url_anticipado)
        self.assertEqual(res_get.status_code, 200)
        self.assertEqual(res_get.context['monto_renta'], Decimal('10000.00'))
        self.assertEqual(res_get.context['monto_servicios'], Decimal('750.00'))
        self.assertEqual(res_get.context['monto_total_adelanto'], Decimal('10750.00'))

        # 3. Registrar el pago anticipado (POST)
        res_post = self.client.post(url_anticipado, {
            'metodo_pago': 'TRANSFERENCIA',
            'fecha_pago': date.today().strftime('%Y-%m-%d'),
            'referencia': 'TXN-ADELANTO-123'
        })
        self.assertEqual(res_post.status_code, 302)

        # 4. Verificar que la factura generada incluye el alquiler + servicios
        factura_adelanto = Factura.objects.filter(contrato=self.contrato1).order_by('-id').first()
        self.assertIsNotNone(factura_adelanto)
        self.assertEqual(factura_adelanto.estado, 'PAGADA')
        self.assertEqual(factura_adelanto.monto_renta, Decimal('10000.00'))
        self.assertEqual(factura_adelanto.monto_servicios, Decimal('750.00'))
        self.assertEqual(factura_adelanto.monto_base, Decimal('10750.00'))
        self.assertEqual(factura_adelanto.detalles_servicios.count(), 1)

        # 5. Verificar que el recibo de pago salda servicios y alquiler
        recibo = factura_adelanto.recibos.first()
        self.assertIsNotNone(recibo)
        self.assertEqual(recibo.monto_pagado, Decimal('10750.00'))
        self.assertEqual(recibo.monto_a_servicios, Decimal('750.00'))
        self.assertEqual(recibo.monto_a_renta, Decimal('10000.00'))

        # 6. Verificar que el recibo impreso no contiene "Mes de Cobertura"
        url_recibo = reverse('imprimir_recibo', args=[recibo.id])
        res_recibo = self.client.get(url_recibo)
        self.assertEqual(res_recibo.status_code, 200)
        self.assertNotIn("Mes de Cobertura:", res_recibo.content.decode('utf-8'))

    def test_smart_cloudinary_storage_resource_types(self):
        from .storage_backends import SmartCloudinaryStorage
        storage = SmartCloudinaryStorage()
        self.assertEqual(storage._get_resource_type('comprobantes/pago.pdf'), 'raw')
        self.assertEqual(storage._get_resource_type('comprobantes/pago.docx'), 'raw')
        self.assertEqual(storage._get_resource_type('fotos/fachada.png'), 'image')
        self.assertEqual(storage._get_resource_type('fotos/sala.jpg'), 'image')







