import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
import io
import os
import logging

logger = logging.getLogger(__name__)


def _extraer_detalles_portafolio(portafolio):
    """Extrae de manera segura los datos de contacto y detalles del portafolio."""
    if not portafolio:
        return "Administración y Gestión de Propiedades"
    detalles = []
    rnc = getattr(portafolio, 'rnc', None)
    if rnc:
        detalles.append(f"RNC: {rnc}")
    tel = getattr(portafolio, 'telefono_contacto', None) or getattr(portafolio, 'telefono', None)
    if tel:
        detalles.append(f"Tel: {tel}")
    email = getattr(portafolio, 'email', None)
    if email:
        detalles.append(f"Correo: {email}")
    eslogan = getattr(portafolio, 'eslogan', None)
    if eslogan:
        detalles.append(eslogan)
    dir_fisica = getattr(portafolio, 'direccion_fisica', None) or getattr(portafolio, 'direccion', None)
    if dir_fisica:
        detalles.append(f"Dirección: {dir_fisica}")
    return "  |  ".join(detalles) if detalles else "Administración y Gestión de Propiedades"


def _insertar_logo_excel(ws, portafolio, anchor='A1'):
    """
    Inserta de forma segura el logo corporativo del portafolio en la celda indicada.
    Soporta archivos locales y remotos (Cloudinary). Tolerante a fallos si no hay conexión o el archivo no existe.
    """
    if not portafolio:
        return False
    logo_field = getattr(portafolio, 'logo_empresa', None) or getattr(portafolio, 'logo', None)
    if not logo_field:
        return False
    try:
        from PIL import Image as PILImage
        from openpyxl.drawing.image import Image as OpenpyxlImage
        import requests

        img_bytes = None
        # 1. Comprobar archivo local si está en disco
        try:
            if hasattr(logo_field, 'path') and os.path.exists(logo_field.path):
                with open(logo_field.path, 'rb') as f:
                    img_bytes = f.read()
        except Exception:
            pass

        # 2. Si no es local, comprobar si el storage puede leerlo
        if not img_bytes and hasattr(logo_field, 'file'):
            try:
                logo_field.open('rb')
                img_bytes = logo_field.read()
            except Exception:
                pass

        # 3. Comprobar URL remota (Cloudinary)
        if not img_bytes and hasattr(logo_field, 'url'):
            url = logo_field.url
            if url and (url.startswith('http://') or url.startswith('https://')):
                try:
                    r = requests.get(url, timeout=3, headers={'User-Agent': 'Mozilla/5.0'})
                    if r.status_code == 200:
                        img_bytes = r.content
                except Exception:
                    pass

        if not img_bytes:
            return False

        pil_img = PILImage.open(io.BytesIO(img_bytes))
        if pil_img.mode not in ('RGB', 'RGBA'):
            pil_img = pil_img.convert('RGBA')

        # Redimensionar proporcionalmente a una altura máxima de 44px y ancho de 160px
        max_h = 44
        ratio = max_h / float(pil_img.height)
        new_w = int(pil_img.width * ratio)
        if new_w > 160:
            ratio_w = 160 / float(new_w)
            new_w = 160
            max_h = int(max_h * ratio_w)

        pil_img_resized = pil_img.resize((new_w, max_h), PILImage.Resampling.LANCZOS)
        out_buf = io.BytesIO()
        pil_img_resized.save(out_buf, format='PNG')
        out_buf.seek(0)

        xl_img = OpenpyxlImage(out_buf)
        xl_img.width = new_w
        xl_img.height = max_h
        ws.add_image(xl_img, anchor)
        return True
    except Exception as e:
        logger.warning(f"No se pudo insertar logo en Excel: {e}")
        return False


def generar_excel_movimientos_detallados(movimientos, total_ingresos, total_gastos, balance_neto, fecha_inicio, fecha_fin, portafolio=None):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Movimientos Detallados"
    
    # Mostrar líneas de cuadrícula
    ws.views.sheetView[0].showGridLines = True

    max_col_num = 7
    max_col_letter = get_column_letter(max_col_num)

    # 1. Intentar insertar el logo del portafolio en A1
    tiene_logo = _insertar_logo_excel(ws, portafolio, anchor='A1')
    start_col_brand = 'B' if tiene_logo else 'A'

    # Fila 1: Nombre de la Empresa / Portafolio
    ws.merge_cells(f'{start_col_brand}1:{max_col_letter}1')
    brand_cell = ws[f'{start_col_brand}1']
    nombre_portafolio = portafolio.nombre.upper() if portafolio and portafolio.nombre else "SISTEMA DE GESTIÓN INMOBILIARIA"
    brand_cell.value = nombre_portafolio
    brand_cell.font = Font(name='Calibri', size=15, bold=True, color='1A252F')
    brand_cell.alignment = Alignment(horizontal='left' if tiene_logo else 'center', vertical='center')
    ws.row_dimensions[1].height = 28

    # Fila 2: Datos de Contacto del Portafolio
    ws.merge_cells(f'{start_col_brand}2:{max_col_letter}2')
    info_cell = ws[f'{start_col_brand}2']
    info_cell.value = _extraer_detalles_portafolio(portafolio)
    info_cell.font = Font(name='Calibri', size=9.5, italic=True, color='555555')
    info_cell.alignment = Alignment(horizontal='left' if tiene_logo else 'center', vertical='center')
    ws.row_dimensions[2].height = 18

    # Fila 3: Banner del Título del Reporte
    ws.merge_cells(f'A3:{max_col_letter}3')
    title_cell = ws['A3']
    title_cell.value = "REPORTE DETALLADO DE INGRESOS Y GASTOS"
    title_cell.font = Font(name='Calibri', size=13, bold=True, color='FFFFFF')
    title_cell.fill = PatternFill(start_color='1A252F', end_color='1A252F', fill_type='solid')
    title_cell.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[3].height = 26

    # Fila 4: Subtítulo Rango de Fechas
    ws.merge_cells(f'A4:{max_col_letter}4')
    sub_cell = ws['A4']
    sub_cell.value = f"Período del {fecha_inicio.strftime('%d/%m/%Y')} al {fecha_fin.strftime('%d/%m/%Y')}"
    sub_cell.font = Font(name='Calibri', size=10.5, italic=True, color='333333')
    sub_cell.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[4].height = 20

    # Fila 5: Espacio en blanco
    ws.row_dimensions[5].height = 8

    # Fila 6: Encabezados de Tabla
    headers = ["Fecha", "Propiedad", "Propietario", "Inquilino / Referencia", "Tipo", "Concepto / Descripción", "Monto (RD$)"]
    for col_num, h_text in enumerate(headers, start=1):
        c = ws.cell(row=6, column=col_num, value=h_text)
        c.fill = PatternFill(start_color='2C3E50', end_color='2C3E50', fill_type='solid')
        c.font = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
        c.alignment = Alignment(horizontal='center', vertical='center')
        c.border = Border(
            left=Side(style='thin', color='DDDDDD'),
            right=Side(style='thin', color='DDDDDD'),
            top=Side(style='thin', color='DDDDDD'),
            bottom=Side(style='thin', color='DDDDDD')
        )
    ws.row_dimensions[6].height = 25

    thin_border = Border(
        left=Side(style='thin', color='DDDDDD'),
        right=Side(style='thin', color='DDDDDD'),
        top=Side(style='thin', color='DDDDDD'),
        bottom=Side(style='thin', color='DDDDDD')
    )

    # Filas de Datos (a partir de la fila 7)
    ingreso_font = Font(color='27AE60', bold=True)
    gasto_font = Font(color='C0392B', bold=True)
    
    for row_idx, m in enumerate(movimientos, start=7):
        fecha_str = m['fecha'].strftime('%d/%m/%Y') if hasattr(m['fecha'], 'strftime') else str(m['fecha'])
        prop_str = f"{m['propiedad']} ({m['grupo_o_residencial']})" if m.get('grupo_o_residencial') else m['propiedad']
        
        ws.append([
            fecha_str,
            prop_str,
            m['propietario'],
            m['persona'],
            m['tipo'],
            m['concepto'],
            float(m['monto'])
        ])
        
        row_cells = ws[row_idx]
        for c_idx, cell in enumerate(row_cells, start=1):
            cell.border = thin_border
            if c_idx == 1:
                cell.alignment = Alignment(horizontal='center')
            elif c_idx == 5:
                cell.alignment = Alignment(horizontal='center')
                if m['tipo'] == 'INGRESO':
                    cell.font = Font(color='27AE60', bold=True)
                else:
                    cell.font = Font(color='C0392B', bold=True)
            elif c_idx == 7:
                cell.number_format = '$#,##0.00;($#,##0.00);"-"'
                cell.alignment = Alignment(horizontal='right')
                if m['tipo'] == 'INGRESO':
                    cell.font = ingreso_font
                else:
                    cell.font = gasto_font

    # Fila de Totales
    current_row = len(movimientos) + 8
    
    ws.cell(row=current_row, column=6, value="TOTAL INGRESOS:").font = Font(bold=True)
    ws.cell(row=current_row, column=6).alignment = Alignment(horizontal='right')
    tot_ing = ws.cell(row=current_row, column=7, value=float(total_ingresos))
    tot_ing.font = Font(color='27AE60', bold=True)
    tot_ing.number_format = '$#,##0.00'
    
    current_row += 1
    ws.cell(row=current_row, column=6, value="TOTAL GASTOS:").font = Font(bold=True)
    ws.cell(row=current_row, column=6).alignment = Alignment(horizontal='right')
    tot_gas = ws.cell(row=current_row, column=7, value=float(total_gastos))
    tot_gas.font = Font(color='C0392B', bold=True)
    tot_gas.number_format = '$#,##0.00'

    current_row += 1
    ws.cell(row=current_row, column=6, value="BALANCE NETO:").font = Font(bold=True, size=12)
    ws.cell(row=current_row, column=6).alignment = Alignment(horizontal='right')
    tot_net = ws.cell(row=current_row, column=7, value=float(balance_neto))
    tot_net.font = Font(color='1A252F', bold=True, size=12)
    tot_net.number_format = '$#,##0.00'

    # Autoajustar ancho de columnas (evaluando filas > 5 para no verse distorsionado por los encabezados)
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            val_str = str(cell.value or '')
            if cell.row > 5 and len(val_str) > max_len:
                max_len = len(val_str)
        ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output.getvalue()


def generar_excel_estado_propiedades_propietario(data):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Estado Propiedades"
    
    ws.views.sheetView[0].showGridLines = True

    portafolio = data.get('portafolio_actual')
    max_col_num = 10
    max_col_letter = get_column_letter(max_col_num)

    # 1. Intentar insertar el logo del portafolio en A1
    tiene_logo = _insertar_logo_excel(ws, portafolio, anchor='A1')
    start_col_brand = 'B' if tiene_logo else 'A'

    # Fila 1: Nombre de la Empresa / Portafolio
    ws.merge_cells(f'{start_col_brand}1:{max_col_letter}1')
    brand_cell = ws[f'{start_col_brand}1']
    nombre_portafolio = portafolio.nombre.upper() if portafolio and portafolio.nombre else "SISTEMA DE GESTIÓN INMOBILIARIA"
    brand_cell.value = nombre_portafolio
    brand_cell.font = Font(name='Calibri', size=15, bold=True, color='1A252F')
    brand_cell.alignment = Alignment(horizontal='left' if tiene_logo else 'center', vertical='center')
    ws.row_dimensions[1].height = 28

    # Fila 2: Datos de Contacto del Portafolio
    ws.merge_cells(f'{start_col_brand}2:{max_col_letter}2')
    info_cell = ws[f'{start_col_brand}2']
    info_cell.value = _extraer_detalles_portafolio(portafolio)
    info_cell.font = Font(name='Calibri', size=9.5, italic=True, color='555555')
    info_cell.alignment = Alignment(horizontal='left' if tiene_logo else 'center', vertical='center')
    ws.row_dimensions[2].height = 18

    # Fila 3: Banner del Título del Documento
    ws.merge_cells(f'A3:{max_col_letter}3')
    title_cell = ws['A3']
    title_cell.value = f"REPORTE MENSUAL DE ESTADO DE PROPIEDADES ({data['nombre_mes'].upper()} {data['anio']})"
    title_cell.font = Font(name='Calibri', size=13, bold=True, color='FFFFFF')
    title_cell.fill = PatternFill(start_color='1A252F', end_color='1A252F', fill_type='solid')
    title_cell.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[3].height = 26

    # Fila 4: Subtítulo de Resumen
    ws.merge_cells(f'A4:{max_col_letter}4')
    sub_cell = ws['A4']
    sub_cell.value = f"Estado consolidado al corte de {data['nombre_mes']} {data['anio']}"
    sub_cell.font = Font(name='Calibri', size=10.5, italic=True, color='333333')
    sub_cell.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[4].height = 20

    # Fila 5: Espacio en blanco
    ws.row_dimensions[5].height = 8

    # Fila 6: Encabezados de Tabla
    headers = [
        "Propiedad", "Propietario", "Inquilino", "Renta Pactada (RD$)",
        "Estado Pago", "Fecha Pago", "Días Atraso", "Monto Cobrado (RD$)",
        "Gastos Directos (RD$)", "Neto Propietario (RD$)"
    ]
    for col_num, h_text in enumerate(headers, start=1):
        c = ws.cell(row=6, column=col_num, value=h_text)
        c.fill = PatternFill(start_color='2C3E50', end_color='2C3E50', fill_type='solid')
        c.font = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
        c.alignment = Alignment(horizontal='center', vertical='center')
        c.border = Border(
            left=Side(style='thin', color='DDDDDD'),
            right=Side(style='thin', color='DDDDDD'),
            top=Side(style='thin', color='DDDDDD'),
            bottom=Side(style='thin', color='DDDDDD')
        )
    ws.row_dimensions[6].height = 24

    thin_border = Border(
        left=Side(style='thin', color='DDDDDD'),
        right=Side(style='thin', color='DDDDDD'),
        top=Side(style='thin', color='DDDDDD'),
        bottom=Side(style='thin', color='DDDDDD')
    )

    # Filas de Datos (a partir de la fila 7)
    for row_idx, item in enumerate(data['reporte_propiedades'], start=7):
        prop_str = f"{item['propiedad_nombre']} ({item['grupo_o_residencial']})" if item.get('grupo_o_residencial') else item['propiedad_nombre']
        ws.append([
            prop_str,
            item['propietario'],
            item['inquilino'],
            float(item['renta_pactada']),
            item['estado_label'],
            item['fecha_pago'] or '-',
            item['dias_retraso'] if item['dias_retraso'] > 0 else '-',
            float(item['monto_pagado']),
            float(item['total_gastos']),
            float(item['monto_neto'])
        ])
        
        row_cells = ws[row_idx]
        for c_idx, cell in enumerate(row_cells, start=1):
            cell.border = thin_border
            if c_idx in [4, 8, 9, 10]:
                cell.number_format = '$#,##0.00;($#,##0.00);"-"'
                cell.alignment = Alignment(horizontal='right')
            elif c_idx in [5, 6, 7]:
                cell.alignment = Alignment(horizontal='center')

    # Fila Totales
    last_row = len(data['reporte_propiedades']) + 8
    tot = data['totales_resumen']
    
    ws.cell(row=last_row, column=3, value="TOTALES GENERALES:").font = Font(bold=True)
    ws.cell(row=last_row, column=3).alignment = Alignment(horizontal='right')
    
    c_pact = ws.cell(row=last_row, column=4, value=float(tot['total_renta_pactada']))
    c_pact.font = Font(bold=True)
    c_pact.number_format = '$#,##0.00'

    c_cob = ws.cell(row=last_row, column=8, value=float(tot['total_cobrado']))
    c_cob.font = Font(bold=True, color='27AE60')
    c_cob.number_format = '$#,##0.00'

    c_gas = ws.cell(row=last_row, column=9, value=float(tot['total_gastos']))
    c_gas.font = Font(bold=True, color='C0392B')
    c_gas.number_format = '$#,##0.00'

    c_net = ws.cell(row=last_row, column=10, value=float(tot['neto_propietario']))
    c_net.font = Font(bold=True, size=11, color='1A252F')
    c_net.number_format = '$#,##0.00'

    # Autoajustar ancho de columnas evaluando filas > 5
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            val_str = str(cell.value or '')
            if cell.row > 5 and len(val_str) > max_len:
                max_len = len(val_str)
        ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output.getvalue()
