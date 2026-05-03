import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'alquilo_core.settings')
django.setup()

from gestion_propiedades.models import PlantillaContrato

html_content = """
<div style="font-family: Arial, sans-serif; text-align: justify; line-height: 1.6;">
    <h2 style="text-align: center;">CONTRATO DE ALQUILER</h2>
    <br>
    <p>
        ENTRE: <strong>{{PROPIETARIO_NOMBRE}}</strong>, dominicano(a), mayor de edad, portador(a) de la cédula de identidad y electoral No. <strong>{{PROPIETARIO_CEDULA}}</strong>, 
        domiciliado(a) y residente en <strong>{{PROPIETARIO_DIRECCION}}</strong>; QUIEN EN LO QUE SIGUE DEL PRESENTE CONTRATO SE DENOMINARÁ, LA PRIMERA PARTE O <strong>EL PROPIETARIO(A)</strong>.
    </p>
    <p>
        Y: <strong>{{INQUILINO_NOMBRE}}</strong>, dominicano(a), mayor de edad, portador(a) de la cédula No. <strong>{{INQUILINO_CEDULA}}</strong>, 
        domiciliado(a) y residente en <strong>{{INQUILINO_DIRECCION}}</strong>; QUIEN EN LO QUE SIGUE DE ESTE CONTRATO SE DENOMINARÁ, LA SEGUNDA PARTE O <strong>EL INQUILINO(A)</strong>.
    </p>
    <p>
        Y EL SEÑOR(A): <strong>{{FIADOR_NOMBRE}}</strong>, dominicano(a), mayor de edad, portador(a) de la cédula de identidad y electoral No. <strong>{{FIADOR_CEDULA}}</strong>, 
        domiciliado(a) y residente en <strong>{{FIADOR_DIRECCION}}</strong>; QUIEN EN LO QUE SIGUE DE ESTE CONTRATO SE DENOMINARÁ, LA TERCERA PARTE O <strong>EL FIADOR SOLIDARIO</strong>.
    </p>

    <h3 style="text-align: center; margin-top: 30px;">SE HA CONVENIDO Y PACTADO LO SIGUIENTE</h3>

    <p><strong>PRIMERO:</strong> El propietario(a) alquila a (el, la) inquilino(a), quien acepta muy conforme el <strong>{{PROPIEDAD_DIRECCION}}</strong>, 
    para ser usada exclusivamente para vivienda.</p>

    <p><strong>SEGUNDO:</strong> EL INQUILINO(A) queda obligado a mantener el inmueble en buen estado, y todos los desperfectos en sus paredes, pisos, 
    puertas, ventanas, cristales, cerraduras, pestillos, instalaciones eléctricas, instalaciones sanitarias (obstrucción de inodoros, lavamanos, bañera, fregaderos, 
    lavaderos, y cualquier otro desagüe, cambio de zapatillas, roturas de llaves, etc.) serán reparados o repuestos a su sólo costo. También queda a cargo de 
    EL INQUILINO(A) la pintura interior del inmueble.</p>

    <p><strong>PARRAFO I:</strong> El dueño tiene derecho a inspeccionar periódicamente el apartamento, máximo 2 visitas anuales, previa notificación al inquilino.</p>

    <p><strong>PARRAFO II:</strong> Se realizará un video al momento de la entrega del apartamento (en presencia del inquilino) y será enviado a ambas partes 
    como constancia de las condiciones entregadas y cómo debe entregarse.</p>

    <p><strong>TERCERO:</strong> EL INQUILINO(A) se compromete a no hacer ningún cambio o distribución nueva en el inmueble sin la previa autorización por escrito 
    del(a) PROPIETARIO(A), y en caso obtenida ésta, las mejoras hechas en el inmueble incluyendo instalaciones eléctricas o sanitarias que hagan, con todos sus materiales, 
    quedarán a beneficio del(a) PROPIETARIO(A).</p>

    <p><strong>CUARTO:</strong> Si durante el curso de este contrato ocurriere entre los moradores del inmueble alquilado algún caso de enfermedad contagiosa y fuere necesario, 
    según opinión de la autoridad competente efectuar la desinfección de dicho inmueble, los gastos originados correrán por cuenta de EL INQUILINO(A), quien además 
    se compromete a velar por el fiel cumplimiento de los reglamentos sanitarios, haciéndose responsable de las infracciones mientras dure este contrato.</p>

    <p><strong>QUINTO:</strong> El alquiler incluye en el monto el pago del servicio de agua. Será de la exclusiva cuenta y riesgo de EL INQUILINO(A), 
    cubrir de manera proporcional, cualquier gasto que se ocasione, así como el pago de los servicios de energía eléctrica, teléfono, basura, Telecable, 
    y cualquier otro servicios ya sean de orden público o privado; estos correrán por cuenta de EL INQUILINO(A).</p>

    <p><strong>SEXTO:</strong> EL INQUILINO(A) se obliga a pagar solidariamente por concepto de alquiler mensual o fracción de mes, la suma de 
    <strong>{{MONTO_RENTA}}</strong>, que se deberá pagar por mes y sin atraso alguno, en el lugar convenido y pactado por las partes 
    para efectuar dicho pago; acordando las partes que se pagará dicha suma durante el tiempo que dure el contrato siempre y cuando el inquilino respete 
    el compromiso pactado entre las partes actuantes. La mensualidad incluye el mantenimiento.</p>

    <p><strong>SEPTIMO:</strong> EL INQUILINO(A), se obliga a entregar a la firma de este contrato la suma de <strong>{{MONTO_DEPOSITO}}</strong>, 
    equivalente a depósitos o fianza.</p>

    <p><strong>OCTAVO:</strong> Este contrato tendrá una vigencia de UN AÑO (1), el cual inicia el día <strong>{{FECHA_INICIO}}</strong> 
    y culmina el día <strong>{{FECHA_FIN}}</strong>.</p>

    <p><strong>PARRAFO I:</strong> El precio del alquiler quedará aumentado de la siguiente forma: EN UN DIEZ PORCIENTO (10%) ANUAL A PARTIR DEL PRIMER AÑO DE ALQUILER 
    de la mensualidad, por cada año que este contrato se renovase por tácita reconducción, es decir, si no fuere denunciado por ninguna de las partes en la fecha de su término, 
    a discreción del PROPIETARIO, el cual si desea hacer valer esta cláusula solo le bastará con enviar los recibos en que consta dichos precios de alquiler aumentados.</p>

    <p><strong>PARRAFO II:</strong> En caso de que EL INQUILINO(A) deseare poner término al contrato antes de la fecha de su terminación, este será sin penalidad. 
    EL INQUILINO(A) deberá notificar a EL PROPIETARIO(A) con treinta (30) días de anticipación a la llegada del término, su decisión de no renovar el contrato de alquiler.</p>

    <p><strong>PARRAFO III:</strong> El pago se efectuará los <strong>{{DIA_PAGO}}</strong> de cada mes. En caso de que el inquilino se retrase dos meses, el propietario tiene derecho al desalojo.</p>

    <p><strong>PARRAFO IV:</strong> El propietario tiene derecho a solicitar el apartamento con 2 meses de antelación.</p>

    <p><strong>PARRAFO V:</strong> El inquilino presenta en calidad de fiador solidario al señor(a): <strong>{{FIADOR_NOMBRE}}</strong>, dominicano(a), mayor de edad, 
    portador(a) de la cédula de identidad y electoral No. <strong>{{FIADOR_CEDULA}}</strong> domiciliado y residente en <strong>{{FIADOR_DIRECCION}}</strong>; 
    lugar de elección de domicilio del fiador, quien acepta conforme ser fiador solidario del inquilino indicado en este contrato, comprometiéndose cabalmente a garantizar a 
    la propietaria del apartamento alquilado todas las obligaciones y deudas que contrajera el inquilino con motivo al presente alquiler, aceptando ser fiador solidario por todo 
    el tiempo que el inquilino ocupe la casa alquilada, renunciando así a lo dispuesto por el Art. 1,740, 2021, 2026, 2034, 2036 del Código Civil Dominicano y art. 32 
    del Código Procesal Civil, todo esto es previsto, en caso de que eventualmente y por cualquier causa la duración de este contrato se extienda más allá de su tiempo. 
    Sea esto de forma voluntaria o involuntaria de la propietaria del apartamento. Es decir, no importando que este contrato se renueve de manera expresa o por tácita reconducción, 
    participe o no participe en dicha renovación el fiador de referencia, éste siempre, sin importar la duración de este contrato, se COMPROMETE Y OBLIGA a cubrir todas las obligaciones 
    que generare la inquilina aludida en este contrato.</p>

    <p><strong>PARRAFO VI:</strong> Que el inquilino acepta y acuerda claramente mediante este contrato que renuncia al derecho indicado en el art. 32 del Código de Procedimiento 
    Civil Dominicano, a favor del arrendador, es decir, de no pedir saneamiento al fiador solidario, en el caso de que dicho fiador el señor(a): <strong>{{FIADOR_NOMBRE}}</strong> 
    haya sido puesto en causa o notificado o demandado conjuntamente con él (el inquilino), para que responda por las obligaciones de los inquilinos como la del mismo fiador en calidad de garante. 
    Generando el presente aspecto contractual una acción o medio de inadmisión a favor del arrendador o propietario y en contra de los inquilinos y el fiador.</p>

    <p><strong>NOVENO:</strong> Queda entendido entre las partes, que el inmueble no se alquila en ninguna circunstancia, por un periodo inferior a UN MES (1), 
    y que las fracciones de mes se cobrarán siempre por mes completo.</p>

    <p><strong>DECIMO:</strong> EL INQUILINO(A) se compromete a hacer entrega de dicho inmueble con los recibos de luz, teléfono, Gas y basura si fuere el caso, 
    pagados al día y de no hacerlo, esta deuda deberá ser pagada inmediatamente con la entrega del mencionado inmueble. Queda entendido y convenido entre las partes, 
    además, que si el inmueble es alquilado con contratos de servicios a nombre de EL PROPIETARIO deberá EL INQUILINO(A) presentar al momento del pago de la renta mensual 
    de alquiler, el recibo pagado al día del servicio correspondiente al último mes.</p>

    <p><strong>PARRAFO I:</strong> Solo se permitirá vivir en el apartamento DOS adultos. De requerir que estas condiciones cambien, tiene que ser notificado al propietario para su autorización.</p>

    <p><strong>DECIMO PRIMERO:</strong> EL PROPIETARIO, garantiza que EL INQUILINO(A) al firmar el presente contrato y cumplir las obligaciones consignadas en el mismo, 
    podrá ocupar pacíficamente y disfrutar del inmueble alquilado, por el término específicamente determinado, mientras cumpla por su parte las condiciones previstas y efectúe 
    con la debida regularidad los pagos mensuales del arrendamiento.</p>

    <p style="margin-top: 40px; text-align: center; font-weight: bold;">
        HECHO Y FIRMADO DE BUENA FE, EN TRES (3) ORIGINALES DE UN MISMO TENOR Y EFECTO, UNO PARA CADA UNA DE LAS PARTES CONTRATANTES. 
        EN LA REPÚBLICA DOMINICANA, A LOS {{DIA_ACTUAL}} DÍAS DEL MES DE {{MES_ACTUAL}} DEL AÑO {{ANIO_ACTUAL}}.
    </p>

    <br><br><br>

    <table style="width: 100%; text-align: center; margin-top: 50px;">
        <tr>
            <td style="width: 50%;">
                ___________________________________________________<br>
                <strong>{{PROPIETARIO_NOMBRE}}</strong><br>
                PROPIETARIO
            </td>
            <td style="width: 50%;">
                ___________________________________________________<br>
                <strong>{{INQUILINO_NOMBRE}}</strong><br>
                INQUILINO
            </td>
        </tr>
    </table>

    <table style="width: 100%; text-align: center; margin-top: 80px;">
        <tr>
            <td style="width: 100%;">
                ___________________________________________________<br>
                <strong>{{FIADOR_NOMBRE}}</strong><br>
                FIADOR SOLIDARIO
            </td>
        </tr>
    </table>

    <br><br><br>

    <p style="text-align: justify; margin-top: 50px;">
        YO, DR. _________________________________________, Abogado Notario, de los del número del ________________________, matrícula No. ____________, certifico y doy Fe 
        que por ante mi comparecieron los señores: <strong>{{PROPIETARIO_NOMBRE}}</strong>, <strong>{{INQUILINO_NOMBRE}}</strong> y <strong>{{FIADOR_NOMBRE}}</strong>, 
        de generales que constan quienes firmaron el presente acto que precede de manera libre y voluntaria, declarándome bajo la fé del juramento que estas son las firmas 
        que utilizan en todos sus actos.
    </p>

    <p style="margin-top: 30px; text-align: center;">
        EN LA REPÚBLICA DOMINICANA, A LOS _____ DÍAS DEL MES DE _________________ DEL AÑO _________.
    </p>

    <div style="text-align: center; margin-top: 80px;">
        _______________________________________________<br>
        <strong>ABOGADO NOTARIO</strong>
    </div>
</div>
"""

plantilla, created = PlantillaContrato.objects.get_or_create(
    titulo="Contrato de Alquiler Residencial (Sistema)",
    es_predeterminada=True,
    defaults={'contenido': html_content}
)
if not created:
    plantilla.contenido = html_content
    plantilla.save()
print("Plantilla por defecto guardada.")
