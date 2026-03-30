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
        
    plain_message = strip_tags(html_content)
    try:
        send_mail(
            subject=asunto,
            message=plain_message,
            from_email=None, # Usa DEFAULT_FROM_EMAIL de settings
            recipient_list=[correo_destino],
            html_message=html_content,
            fail_silently=False,
        )
        return True
    except Exception as e:
        logger.error(f"Error enviando correo a {correo_destino}: {e}")
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
    cliente = factura_saas.usuario
    if not cliente.email:
        return False
        
    asunto = "💳 Resumen de Facturación SaaS - Alquilo"
    
    cuerpo = f"""
        <p>Hola <strong>{cliente.first_name}</strong>,</p>
        <p>Tu corte del sistema ha sido procesado. Este es el detalle del mes de uso de la plataforma:</p>
        <ul>
            <li>Propiedades Activas Monetizadas: <strong>{factura_saas.propiedades_cobradas}</strong></li>
            <li>Tarifa SaaS por unidad: <strong>$1.00</strong></li>
        </ul>
        <div style="background-color: #e8f4fd; padding: 15px; border-radius: 5px; margin: 20px 0;">
            <p style="margin: 0;">Total a pagar: <strong>${factura_saas.monto_total}</strong></p>
            <p style="margin: 5px 0 0 0; font-size: 12px;">Vence el: {factura_saas.fecha_vencimiento.strftime('%d/%m/%Y')}</p>
        </div>
        <p>Mantén tu suscripción activa para garantizar el control automático del robot de cobros para tu portafolio.</p>
    """
    
    html = _generar_plantilla_html(
        titulo="Recibo Comercial B2B", 
        parrafos_html=cuerpo, 
        link_texto="Abrir Master Control", 
        link_url=f"{BASE_URL}/master-control/"
    )
    return _enviar_correo_seguro(asunto, cliente.email, html)
