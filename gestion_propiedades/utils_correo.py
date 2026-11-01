import os
import logging
from django.core.mail import send_mail
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)

# Dominio dinámico (Fallback para local)
BASE_URL = f"https://{os.environ.get('CUSTOM_DOMAIN', 'alquilosoftware.com')}"

def _generar_plantilla_html(titulo, parrafos_html, link_texto=None, link_url=None):
    """ Genera un HTML limpio y empresarial para los correos """
    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; border: 1px solid #e0e0e0; border-radius: 8px; overflow: hidden;">
        <div style="background-color: #1a252f; padding: 20px; text-align: center;">
            <h2 style="color: #ffffff; margin: 0;">Alquilo Software</h2>
            <p style="color: #f39c12; margin: 5px 0 0 0; font-size: 14px;">{titulo}</p>
        </div>
        <div style="padding: 30px; color: #333333; line-height: 1.6;">
            {parrafos_html}
    """
    
    if link_texto and link_url:
        html += f"""
            <div style="text-align: center; margin-top: 30px;">
                <a href="{link_url}" style="background-color: #f39c12; color: #1a252f; padding: 12px 25px; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block;">
                    {link_texto}
                </a>
            </div>
        """
        
    html += """
        </div>
        <div style="background-color: #f8f9fa; padding: 15px; text-align: center; font-size: 12px; color: #7f8c8d;">
            <p>Este es un aviso automático generado por el motor financiero. Si notas algún error, contacta a tu arrendador.</p>
        </div>
    </div>
    """
    return html

def _enviar_correo_seguro(asunto, correo_destino, html_content):
    if not correo_destino:
        return False
        
    try:
        from django.conf import settings
        import requests
        import json
        
        api_key = getattr(settings, 'EMAIL_HOST_PASSWORD', None) or os.environ.get('SENDGRID_API_KEY', '')
        if api_key:
            url = "https://api.sendgrid.com/v3/mail/send"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            
            em_from = getattr(settings, 'DEFAULT_FROM_EMAIL', 'Alquilo Software <noreply@alquilosoftware.com>')
            origen = {"email": em_from.split('<')[1].replace('>','').strip(), "name": em_from.split('<')[0].strip()} if '<' in em_from else {"email": em_from}
                
            payload = {
                "personalizations": [{"to": [{"email": correo_destino}]}],
                "from": origen,
                "subject": asunto,
                "content": [{"type": "text/html", "value": html_content}]
            }
            
            resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=5)
            if resp.status_code in (200, 202):
                return True
            logger.warning(f"SendGrid API devolvió status {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.error(f"Error enviando correo a {correo_destino} por Web API: {e}")

    # Fallback si SendGrid falla o no está configurado (por ejemplo en entorno de pruebas)
    try:
        from django.core.mail import send_mail
        from django.conf import settings
        backend = getattr(settings, 'EMAIL_BACKEND', '')
        if 'locmem' in backend or 'console' in backend or getattr(settings, 'EMAIL_HOST_USER', None):
            em_from = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@alquilosoftware.com')
            send_mail(
                asunto,
                strip_tags(html_content),
                em_from,
                [correo_destino],
                html_message=html_content,
                fail_silently=True
            )
            return True
    except Exception as e2:
        logger.error(f"Error fallback send_mail: {e2}")
        
    return False

def enviar_correo_con_adjunto(asunto, correo_destino, html_content, archivo_bytes, nombre_archivo, mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"):
    if not correo_destino:
        return False
        
    try:
        from django.conf import settings
        import requests
        import json
        import base64
        
        encoded_file = base64.b64encode(archivo_bytes).decode('utf-8')
        api_key = getattr(settings, 'EMAIL_HOST_PASSWORD', None) or os.environ.get('SENDGRID_API_KEY', '')
        
        if api_key:
            url = "https://api.sendgrid.com/v3/mail/send"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            
            em_from = getattr(settings, 'DEFAULT_FROM_EMAIL', 'Alquilo Software <noreply@alquilosoftware.com>')
            origen = {"email": em_from.split('<')[1].replace('>','').strip(), "name": em_from.split('<')[0].strip()} if '<' in em_from else {"email": em_from}
                
            payload = {
                "personalizations": [{"to": [{"email": correo_destino}]}],
                "from": origen,
                "subject": asunto,
                "content": [{"type": "text/html", "value": html_content}],
                "attachments": [
                    {
                        "content": encoded_file,
                        "filename": nombre_archivo,
                        "type": mime_type,
                        "disposition": "attachment"
                    }
                ]
            }
            
            resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=5)
            if resp.status_code in (200, 202):
                return True
            logger.warning(f"SendGrid API con adjunto devolvió status {resp.status_code}: {resp.text}")
            
    except Exception as e:
        logger.error(f"Error enviando correo con adjunto a {correo_destino} por Web API: {e}")
        
    try:
        from django.core.mail import EmailMessage
        from django.conf import settings
        backend = getattr(settings, 'EMAIL_BACKEND', '')
        if 'locmem' in backend or 'console' in backend or getattr(settings, 'EMAIL_HOST_USER', None):
            em_from = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@alquilosoftware.com')
            msg = EmailMessage(asunto, html_content, em_from, [correo_destino])
            msg.content_subtype = "html"
            msg.attach(nombre_archivo, archivo_bytes, mime_type)
            msg.send(fail_silently=True)
            return True
    except Exception as e2:
        logger.error(f"Error fallback EmailMessage con adjunto: {e2}")

    return False

# --- CASOS DE USO (B2C: RENTAS Y MORAS) ---

def enviar_aviso_factura_generada(factura):
    inquilino = factura.contrato.inquilino
    if not inquilino or not inquilino.recibir_alertas_correo or not inquilino.correo:
        return False
        
    portafolio_nombre = factura.contrato.propiedad.portafolio.nombre
    asunto = f"Nueva Factura Disponible - {portafolio_nombre}"
    
    cuerpo = f"""
        <p>Hola <strong>{inquilino.nombre}</strong>,</p>
        <p>Tu factura de renta para la propiedad <strong>{factura.contrato.propiedad.nombre_o_numero}</strong> ha sido generada exitosamente.</p>
        <ul style="list-style: none; padding: 0;">
            <li>💰 <strong>Monto Base:</strong> ${factura.monto_base}</li>
            <li>📅 <strong>Fecha Límite:</strong> {factura.fecha_vencimiento.strftime('%d/%m/%Y')}</li>
            <li>📝 <strong>Concepto:</strong> {factura.concepto}</li>
        </ul>
        <p>Por favor realiza el pago antes de la fecha límite para evitar cargos por mora administrativa.</p>
    """
    
    html = _generar_plantilla_html(
        titulo="Estado de Cuenta", 
        parrafos_html=cuerpo, 
        link_texto="Ir al Portal y Pagar", 
        link_url=f"{BASE_URL}/portal/login/"
    )
    return _enviar_correo_seguro(asunto, inquilino.correo, html)

def enviar_aviso_vencimiento_cercano(factura):
    inquilino = factura.contrato.inquilino
    if not inquilino or not inquilino.recibir_alertas_correo or not inquilino.correo:
        return False
        
    asunto = "⚠️ Tu periodo de gracia finaliza mañana"
    
    cuerpo = f"""
        <p>Hola <strong>{inquilino.nombre}</strong>,</p>
        <p>Te recordamos que el periodo de gracia para tu pago de <strong>${factura.monto_base}</strong> finaliza el día de mañana.</p>
        <p>A partir del día posterior al vencimiento ({factura.fecha_vencimiento.strftime('%d/%m/%Y')}), el sistema aplicará automáticamente el cargo adicional por mora pactado en tu contrato ({factura.contrato.porcentaje_mora}%).</p>
        <p>Si ya realizaste el pago, ignora este mensaje y repórtalo en tu portal.</p>
    """
    
    html = _generar_plantilla_html(
        titulo="Aviso Preventivo de Vencimiento", 
        parrafos_html=cuerpo, 
        link_texto="Consultar Balance", 
        link_url=f"{BASE_URL}/portal/login/"
    )
    return _enviar_correo_seguro(asunto, inquilino.correo, html)

def enviar_aviso_mora_aplicada(factura, mora_obj):
    inquilino = factura.contrato.inquilino
    if not inquilino or not inquilino.recibir_alertas_correo or not inquilino.correo:
        return False
        
    nuevo_total = factura.monto_base + mora_obj.monto
    asunto = "🚨 Cargo por Mora Aplicado a tu cuenta"
    
    cuerpo = f"""
        <p>Hola <strong>{inquilino.nombre}</strong>,</p>
        <p>El periodo de gracia para tu factura ha caducado sin recibir confirmación de pago.</p>
        <p>Por lo tanto, se ha aplicado un recargo por mora administrativa de <strong>${mora_obj.monto}</strong>.</p>
        <div style="background-color: #ffd8d8; padding: 15px; border-radius: 5px; margin: 20px 0; text-align: center;">
            <h3 style="color: #c0392b; margin: 0;">Nuevo Saldo a Pagar: ${float(nuevo_total)}</h3>
        </div>
        <p>Este saldo deberá ser cubierto a la brevedad posible para evitar acumulación de recargos mensuales.</p>
    """
    
    html = _generar_plantilla_html(
        titulo="Estado de Cuenta Actualizado", 
        parrafos_html=cuerpo, 
        link_texto="Consultar Saldo y Pagar", 
        link_url=f"{BASE_URL}/portal/login/"
    )
    return _enviar_correo_seguro(asunto, inquilino.correo, html)

# --- CASOS DE USO (B2B SAAS) ---

def enviar_aviso_factura_saas(factura_saas):
    """
    Notificación formal de emisión de factura mensual B2B.
    Se envía EXCLUSIVAMENTE al Administrador de la cuenta.
    """
    cliente = factura_saas.usuario
    if not cliente.email:
        return False
        
    try:
        sub = cliente.suscripcion
        nombre_plan = sub.plan_saas.nombre if sub.plan_saas else 'Estándar'
        dias_gracia = sub.plan_saas.dias_gracia_habiles if sub.plan_saas else 15
    except Exception:
        nombre_plan = 'Estándar'
        dias_gracia = 15

    asunto = f"💳 Factura Mensual Emitida - Plan {nombre_plan} - Alquilo Software"
    
    cuerpo = f"""
        <p>Estimado/a <strong>{cliente.get_full_name() or cliente.first_name}</strong>,</p>
        <p>Hemos generado tu factura mensual de servicio para la administración de tu portafolio en <strong>Alquilo Software</strong>.</p>
        
        <table style="width: 100%; border-collapse: collapse; margin: 15px 0; font-size: 14px;">
            <tr style="border-bottom: 1px solid #e2e8f0;">
                <td style="padding: 8px 0; color: #64748b;">Plan Contratado:</td>
                <td style="padding: 8px 0; font-weight: bold; text-align: right; color: #1e293b;">{nombre_plan}</td>
            </tr>
            <tr style="border-bottom: 1px solid #e2e8f0;">
                <td style="padding: 8px 0; color: #64748b;">Propiedades Gestionadas:</td>
                <td style="padding: 8px 0; font-weight: bold; text-align: right; color: #1e293b;">{factura_saas.propiedades_cobradas} unidades</td>
            </tr>
            {f'<tr style="border-bottom: 1px solid #e2e8f0;"><td style="padding: 8px 0; color: #64748b;">Usuarios Asistentes Extra:</td><td style="padding: 8px 0; font-weight: bold; text-align: right; color: #1e293b;">{factura_saas.usuarios_cobrados}</td></tr>' if factura_saas.usuarios_cobrados > 0 else ''}
            <tr style="border-bottom: 2px solid #0f172a;">
                <td style="padding: 10px 0; font-weight: bold; color: #0f172a; font-size: 16px;">Total a Pagar:</td>
                <td style="padding: 10px 0; font-weight: bold; text-align: right; color: #16a34a; font-size: 18px;">${factura_saas.monto_total} USD</td>
            </tr>
        </table>
        
        <div style="background-color: #f8fafc; border-left: 4px solid #3b82f6; padding: 12px 16px; border-radius: 4px; margin: 15px 0;">
            <p style="margin: 0; font-size: 13px; color: #334155;">
                📅 <strong>Plazo de Pago:</strong> Dispones de <strong>{dias_gracia} días hábiles</strong> para efectuar el pago.<br>
                Fecha límite: <strong>{factura_saas.fecha_vencimiento.strftime('%d/%m/%Y')}</strong>.
            </p>
        </div>

        <p style="font-size: 13px; color: #475569; margin-top: 15px;">
            <strong>Cuentas Bancarias Disponibles:</strong><br>
            • <strong>Dólares (US$):</strong> BHD: <code>08931700066</code><br>
            • <strong>Pesos (RD$):</strong> BHD: <code>08931700040</code> | Reservas: <code>0302102948</code> | Popular: <code>750927543</code>
        </p>
        <p style="font-size: 12px; color: #94a3b8;">Una vez realizada la transferencia, puedes adjuntar tu comprobante directamente desde tu panel.</p>
    """
    
    html = _generar_plantilla_html(
        titulo="Factura B2B Mensual", 
        parrafos_html=cuerpo, 
        link_texto="Ver Factura y Subir Comprobante", 
        link_url=f"{BASE_URL}/mi-suscripcion/"
    )
    return _enviar_correo_seguro(asunto, cliente.email, html)


def enviar_recordatorio_factura_saas(factura_saas, dias_habiles_restantes):
    """
    Recordatorio amistoso y no intrusivo de vencimiento de factura SaaS.
    Se envía EXCLUSIVAMENTE al Administrador titular.
    """
    cliente = factura_saas.usuario
    if not cliente.email:
        return False
        
    if dias_habiles_restantes == 1:
        asunto = "⚠️ Aviso Preventivo: Tu factura de Alquilo Software vence mañana"
        mensaje_tiempo = "vence el día de <strong>mañana</strong> (1 día hábil restante)"
    else:
        asunto = f"🔔 Recordatorio Amistoso: Tu factura de Alquilo Software vence en {dias_habiles_restantes} días laborables"
        mensaje_tiempo = f"vence en <strong>{dias_habiles_restantes} días hábiles</strong>"

    cuerpo = f"""
        <p>Hola <strong>{cliente.get_full_name() or cliente.first_name}</strong>,</p>
        <p>Te enviamos este recordatorio cordial de que tu factura mensual por <strong>${factura_saas.monto_total} USD</strong> {mensaje_tiempo} (Fecha límite: <strong>{factura_saas.fecha_vencimiento.strftime('%d/%m/%Y')}</strong>).</p>
        
        <p>Para garantizar la continuidad ininterrumpida de las automatizaciones de cobro y contratos de tu portafolio, recuerda reportar tu pago antes de la fecha límite.</p>
        
        <div style="background-color: #f1f5f9; padding: 12px 15px; border-radius: 6px; margin: 15px 0; font-size: 13px;">
            <p style="margin: 0; color: #475569;">
                <strong>Cuentas Bancarias:</strong><br>
                • US$: BHD <code>08931700066</code><br>
                • RD$: BHD <code>08931700040</code> | Reservas <code>0302102948</code> | Popular <code>750927543</code>
            </p>
        </div>
        <p style="font-size: 12px; color: #64748b;">Si ya realizaste la transferencia y subiste tu comprobante, por favor haz caso omiso a este mensaje.</p>
    """
    
    html = _generar_plantilla_html(
        titulo="Recordatorio de Facturación", 
        parrafos_html=cuerpo, 
        link_texto="Adjuntar Comprobante de Pago", 
        link_url=f"{BASE_URL}/mi-suscripcion/"
    )
    return _enviar_correo_seguro(asunto, cliente.email, html)


def enviar_aviso_suspension_saas(factura_saas):
    """
    Notificación respetuosa de suspensión por vencimiento cumplido sin pago.
    Se envía EXCLUSIVAMENTE al Administrador titular.
    """
    cliente = factura_saas.usuario
    if not cliente.email:
        return False
        
    asunto = "⏸️ Servicio en Pausa Temporal - Alquilo Software"
    cuerpo = f"""
        <p>Estimado/a <strong>{cliente.get_full_name() or cliente.first_name}</strong>,</p>
        <p>Te informamos que el plazo de pago para la factura #{factura_saas.id} (${factura_saas.monto_total} USD) venció el pasado <strong>{factura_saas.fecha_vencimiento.strftime('%d/%m/%Y')}</strong>, por lo que el acceso a la plataforma se encuentra pausado temporalmente.</p>
        
        <div style="background-color: #ecfdf5; border-left: 4px solid #10b981; padding: 12px 16px; border-radius: 4px; margin: 15px 0;">
            <p style="margin: 0; font-weight: bold; color: #065f46;">¡Tus datos están 100% seguros y respaldados!</p>
            <p style="margin: 4px 0 0 0; font-size: 13px; color: #047857;">Toda la información de tus 132 inmuebles, inquilinos, contratos y estados de cuenta se encuentra intacta y bajo máxima seguridad.</p>
        </div>

        <p>Para restablecer el acceso de tu equipo de inmediato, puedes subir tu comprobante de transferencia o contactarnos directamente por WhatsApp.</p>
    """
    
    html = _generar_plantilla_html(
        titulo="Pausa Preventiva de Servicio", 
        parrafos_html=cuerpo, 
        link_texto="💬 Hablar por WhatsApp para Reactivar", 
        link_url="https://wa.me/18493532097"
    )
    return _enviar_correo_seguro(asunto, cliente.email, html)

def enviar_aviso_trial_por_vencer(cliente, dias=3):
    if not cliente.email: return False
    asunto = f"⏳ Tu prueba de Alquilo Software termina en {dias} días"
    cuerpo = f"""
        <p>Hola <strong>{cliente.first_name}</strong>,</p>
        <p>Esperamos que estés disfrutando automatizar tu negocio de alquileres. Te escribimos para avisarte que <strong>tu cuenta de prueba gratuita expira en {dias} días.</strong></p>
        <p>Si deseas continuar usando la plataforma para administrar tu portafolio, por favor ponte en contacto conmigo directamente a mi WhatsApp oficial o respondiedo este correo.</p>
    """
    html = _generar_plantilla_html(
        titulo="Aviso de Prueba Gratuita", 
        parrafos_html=cuerpo, 
        link_texto="💬 Contactar por WhatsApp", 
        link_url="https://wa.me/18493532097"
    )
    return _enviar_correo_seguro(asunto, cliente.email, html)

def enviar_aviso_trial_vencido(cliente):
    if not cliente.email: return False
    asunto = "⛔ Tu período de prueba ha caducado - Suspensión de Acceso"
    cuerpo = f"""
        <p>Hola <strong>{cliente.first_name}</strong>,</p>
        <p>El período de tiempo asignado a tu cuenta de prueba ha finalizado oficialmente y <strong>el acceso a tu panel ha sido suspendido de forma preventiva</strong>.</p>
        <div style="background-color: #fff3cd; padding: 15px; border-radius: 5px; border-left: 5px solid #ffecb5; margin: 20px 0;">
            <p style="margin: 0; color: #856404; font-weight: bold;">¡No te preocupes!</p>
            <p style="margin: 5px 0 0 0; color: #856404;">La información de tu cuenta, contratos y propiedades no se ha perdido. Todo está seguro y protegido en la nube.</p>
        </div>
        <p>Sin embargo, necesitas reactivar tu cuenta para continuar usando la plataforma. Por favor ponte en contacto conmigo inmediatamente vía WhatsApp para restablecer tu acceso y asignarte tu Plan Profesional.</p>
    """
    html = _generar_plantilla_html(
        titulo="Suspensión Temporal de Servicio", 
        parrafos_html=cuerpo, 
        link_texto="💬 Hablar por WhatsApp para Reactivar", 
        link_url="https://wa.me/18493532097"
    )
    return _enviar_correo_seguro(asunto, cliente.email, html)

def enviar_alerta_nuevo_registro_admin(cliente, nombre_portafolio, telefono):
    """Faro pasivo que notifica al administrador maestro que hay un nuevo cliente."""
    admin_email = "jreynoso280988@gmail.com"
    asunto = "🔥 ¡Nuevo Inversor Registrado en Alquilo Software!"
    cuerpo = f"""
        <div style="background-color: #e8f5e9; padding: 15px; border-radius: 5px; border-left: 5px solid #4caf50; margin: 20px 0;">
            <p style="margin: 0; color: #2e7d32; font-weight: bold;">Un prospecto ha activado la Máquina de 45 Días.</p>
        </div>
        <p><strong>Detalles del Cliente Orgánico:</strong></p>
        <ul>
            <li><strong>Nombre:</strong> {cliente.first_name} {cliente.last_name}</li>
            <li><strong>Correo:</strong> {cliente.email}</li>
            <li><strong>Nombre del Negocio B2B:</strong> {nombre_portafolio}</li>
            <li><strong>Teléfono / WhatsApp:</strong> {telefono if telefono else 'No provisto'}</li>
        </ul>
        <p>El sistema ya le asignó su fecha de expiración automática y lo conectó al ecosistema. ¡A vender!</p>
    """
    html = _generar_plantilla_html(
        titulo="Alarma del Sistema SaaS", 
        parrafos_html=cuerpo, 
        link_texto="Escribirle a este Prospecto", 
    )
    return _enviar_correo_seguro(asunto, admin_email, html)

def enviar_reporte_diario_admin(estadisticas):
    """
    Reporte B2B enviado al SuperAdministrador resumiendo la ejecución de facturar_saas_diario.py.
    """
    admin_email = "jreynoso280988@gmail.com"
    asunto = f"🤖 Resumen del Motor Financiero - {estadisticas.get('fecha', '')}"
    
    cuerpo = f"""
        <div style="background-color: #2c3e50; padding: 15px; border-radius: 5px; margin: 20px 0; color: white; text-align: center;">
            <h3 style="margin: 0; color: #f1c40f;">Reporte del Cron Job Completado</h3>
        </div>
        <p><strong>Resultados del Barrido Automático de Hoy:</strong></p>
        <ul style="line-height: 1.8;">
            <li>💼 <strong>SaaS B2B Emitidas:</strong> {estadisticas.get('facturas_saas', 0)} recibos de dueños.</li>
            <li>🏠 <strong>Rentas B2C Emitidas:</strong> {estadisticas.get('facturas_b2c', 0)} facturas de inquilinos.</li>
            <li>⚖️ <strong>Moras Aplicadas:</strong> {estadisticas.get('moras', 0)} recargos morosos inyectados.</li>
            <li>🔔 <strong>Avisos Envío:</strong> {estadisticas.get('recordatorios', 0)} preventivos a inquilinos.</li>
            <li>⏳ <strong>Trials Avisados:</strong> {estadisticas.get('trials_avisados', 0)} dueños notificados.</li>
            <li>🚫 <strong>Trials Suspendidos:</strong> {estadisticas.get('trials_suspendidos', 0)} cuentas bloqueadas por vencimiento.</li>
        </ul>
        <p>El sistema automático ha operado con normalidad y los correos han sido distribuidos exitosamente a los destinatarios.</p>
    """
    html = _generar_plantilla_html(
        titulo="Reporte Ejecutivo B2B", 
        parrafos_html=cuerpo, 
        link_texto="Ir al Centro de Mando", 
        link_url=f"{BASE_URL}/master-control/"
    )
    return _enviar_correo_seguro(asunto, admin_email, html)
