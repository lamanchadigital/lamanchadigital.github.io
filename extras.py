import os, sys, math, datetime
import requests
from PIL import Image, ImageDraw, ImageOps
import main

main.COLORES['clima'] = '#12507B'
main.NOMBRES['clima'] = 'El tiempo'
NL = main.NL
AMARILLO = '#FFC83D'
NUBE = '#F2F5F8'
AGUA = '#8FD0FF'


def tg_foto(ruta, texto):
    with open(ruta, 'rb') as f:
        r = requests.post(main.TG + '/sendPhoto',
                          data={'chat_id': main.CHAT, 'caption': texto[:1000]},
                          files={'photo': f}, timeout=60)
    if not r.ok:
        print('Respuesta de Telegram:', r.status_code, r.text[:300])
    r.raise_for_status()


def fondo_foto(seccion, clave, color, ancho, alto):
    fondo, vez = main.elegir_fondo(seccion, clave)
    if fondo:
        try:
            foto = ImageOps.exif_transpose(Image.open(fondo)).convert('RGB')
            if vez % 2 == 1:
                foto = ImageOps.mirror(foto)
            zoom = 1 + 0.15 * (vez % 3)
            if zoom > 1:
                w, h = foto.size
                cw, ch = int(w / zoom), int(h / zoom)
                x0 = int((w - cw) * (0.3 if vez % 2 == 0 else 0.7))
                y0 = int((h - ch) * 0.5)
                foto = foto.crop((x0, y0, x0 + cw, y0 + ch))
            foto = ImageOps.fit(foto, (ancho, alto))
            img = Image.blend(foto, Image.new('RGB', (ancho, alto), color), main.INTENSIDAD)
            return img, True
        except Exception as ex:
            print('No se pudo usar el fondo:', fondo, ex)
    return Image.new('RGB', (ancho, alto), color), False


def dibujar_sol(d, cx, cy, r):
    grosor = max(5, int(r * 0.16))
    for i in range(8):
        a = i * math.pi / 4
        d.line([cx + math.cos(a) * r * 1.35, cy + math.sin(a) * r * 1.35,
                cx + math.cos(a) * r * 1.8, cy + math.sin(a) * r * 1.8],
               fill=AMARILLO, width=grosor)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=AMARILLO)


def dibujar_nube(d, x, y, w, color):
    h = w * 0.55
    d.ellipse([x, y + h * 0.35, x + w * 0.5, y + h], fill=color)
    d.ellipse([x + w * 0.25, y, x + w * 0.75, y + h * 0.8], fill=color)
    d.ellipse([x + w * 0.5, y + h * 0.3, x + w, y + h], fill=color)
    d.rectangle([x + w * 0.25, y + h * 0.55, x + w * 0.75, y + h], fill=color)


def tipo_cielo(c):
    if c in (0, 1):
        return 'sol'
    if c == 2:
        return 'parcial'
    if c == 3:
        return 'nublado'
    if c in (45, 48):
        return 'niebla'
    if 51 <= c <= 67 or 80 <= c <= 82:
        return 'lluvia'
    if 71 <= c <= 77 or c in (85, 86):
        return 'nieve'
    if c >= 95:
        return 'tormenta'
    return 'parcial'


def icono_cielo(d, codigo, cx, cy, s):
    tipo = tipo_cielo(codigo)
    grosor = max(6, int(s * 0.07))
    if tipo == 'sol':
        dibujar_sol(d, cx, cy, s * 0.45)
    elif tipo == 'parcial':
        dibujar_sol(d, cx - s * 0.3, cy - s * 0.3, s * 0.32)
        dibujar_nube(d, cx - s * 0.7, cy - s * 0.15, s * 1.4, NUBE)
    elif tipo == 'nublado':
        dibujar_nube(d, cx - s * 0.9, cy - s * 0.5, s * 1.3, '#C9D2DB')
        dibujar_nube(d, cx - s * 0.5, cy - s * 0.2, s * 1.4, NUBE)
    elif tipo == 'niebla':
        dibujar_nube(d, cx - s * 0.7, cy - s * 0.7, s * 1.4, NUBE)
        for i in range(3):
            y = cy + s * 0.15 + i * s * 0.22
            d.line([cx - s * 0.7, y, cx + s * 0.7, y], fill=NUBE, width=grosor)
    else:
        dibujar_nube(d, cx - s * 0.7, cy - s * 0.8, s * 1.4, NUBE)
        if tipo == 'lluvia':
            for i in range(5):
                x = cx - s * 0.5 + i * s * 0.25
                d.line([x, cy + s * 0.05, x - s * 0.12, cy + s * 0.5], fill=AGUA, width=grosor)
        elif tipo == 'nieve':
            for i in range(5):
                x = cx - s * 0.5 + i * s * 0.25
                y = cy + s * 0.15 + (i % 2) * s * 0.22
                r = s * 0.06
                d.ellipse([x - r, y - r, x + r, y + r], fill='white')
        else:
            rayo = [(cx + s * 0.05, cy - s * 0.05), (cx - s * 0.25, cy + s * 0.45),
                    (cx - s * 0.02, cy + s * 0.45), (cx - s * 0.15, cy + s * 0.9),
                    (cx + s * 0.3, cy + s * 0.25), (cx + s * 0.07, cy + s * 0.25)]
            d.polygon(rayo, fill=AMARILLO)


def icono_diario(d, cx, cy, s):
    d.rounded_rectangle([cx - s * 0.6, cy - s * 0.7, cx + s * 0.6, cy + s * 0.7],
                        radius=int(s * 0.08), fill='white')
    d.rectangle([cx - s * 0.45, cy - s * 0.55, cx + s * 0.45, cy - s * 0.25], fill='#0F2A43')
    for i in range(5):
        y = cy - s * 0.05 + i * s * 0.17
        d.line([cx - s * 0.45, y, cx + s * 0.45, y], fill='#8896A5', width=max(4, int(s * 0.05)))


def recortar(d, texto, fuente, ancho_max):
    if d.textlength(texto, font=fuente) <= ancho_max:
        return texto
    while texto and d.textlength(texto + '…', font=fuente) > ancho_max:
        texto = texto[:-1]
    return texto.rstrip() + '…'


def marco(d, ancho, alto, etiqueta, hay_foto):
    d.rectangle([0, 0, 28, alto], fill=main.ROJO)
    d.rectangle([0, alto - 100, ancho, alto], fill='#0A1B2C')
    f_et = main.fuente(30)
    w_et = d.textlength(etiqueta, font=f_et)
    d.rectangle([70, 55, 70 + w_et + 36, 110], fill=main.ROJO)
    d.text((88, 62), etiqueta, font=f_et, fill='white')
    if hay_foto:
        ilus = 'IMAGEN ILUSTRATIVA'
        f_ilus = main.fuente(20)
        d.text((ancho - 70 - d.textlength(ilus, font=f_ilus), 72), ilus,
               font=f_ilus, fill='#DDE3EA')
    d.text((70, alto - 68), 'LA MANCHA DIGITAL', font=main.fuente(34), fill='white')
    lugar = 'Palpalá, Jujuy'
    f_lugar = main.fuente(28)
    d.text((ancho - 70 - d.textlength(lugar, font=f_lugar), alto - 64),
           lugar, font=f_lugar, fill='#B8C4D0')


def crear_placa_clima(minima, maxima, cielo, lluvia, codigo, texto_fecha, seccion, ruta):
    ancho, alto = 1200, 675
    img, hay_foto = fondo_foto(seccion, texto_fecha, main.COLORES['clima'], ancho, alto)
    d = ImageDraw.Draw(img)
    marco(d, ancho, alto, 'EL TIEMPO EN PALPALÁ', hay_foto)
    d.text((70, 125), texto_fecha[0].upper() + texto_fecha[1:], font=main.fuente(40), fill='white')
    f_max = main.fuente(190)
    t_max = str(maxima) + '°'
    d.text((70, 170), t_max, font=f_max, fill='white')
    x2 = 70 + d.textlength(t_max, font=f_max) + 50
    d.text((x2, 215), 'Máxima', font=main.fuente(36), fill='#DDE3EA')
    d.text((x2, 265), 'Mínima ' + str(minima) + '°', font=main.fuente(52), fill='white')
    d.text((70, 420), 'Cielo ' + cielo, font=main.fuente(46), fill='white')
    if lluvia is not None:
        d.text((70, 485), 'Probabilidad de lluvia: ' + str(lluvia) + '%',
               font=main.fuente(38), fill='#DDE3EA')
    icono_cielo(d, codigo, 990, 300, 170)
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    img.save(ruta, quality=88)


def crear_placa_resumen(texto_fecha, titulos, ruta):
    ancho, alto = 1200, 675
    img, hay_foto = fondo_foto('resumen', texto_fecha, main.COLORES['resumen'], ancho, alto)
    d = ImageDraw.Draw(img)
    marco(d, ancho, alto, 'RESUMEN DEL DÍA', hay_foto)
    d.text((70, 125), texto_fecha[0].upper() + texto_fecha[1:], font=main.fuente(40), fill='white')
    total = len(titulos)
    if total == 1:
        encabezado = '1 nota publicada hoy'
    else:
        encabezado = str(total) + ' notas publicadas hoy'
    d.text((70, 180), encabezado, font=main.fuente(56), fill='white')
    f_t = main.fuente(34)
    y = 275
    for t in titulos[:4]:
        d.text((70, y), recortar(d, '• ' + t, f_t, 800), font=f_t, fill='white')
        y += 62
    if total > 4:
        d.text((70, y), 'y ' + str(total - 4) + ' más en nuestra web', font=main.fuente(30), fill='#DDE3EA')
    icono_diario(d, 1010, 250, 120)
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    img.save(ruta, quality=88)


def clima_social(e, prueba=False):
    zona = datetime.timezone(datetime.timedelta(hours=-3))
    ahora = datetime.datetime.now(zona)
    fecha = ahora.strftime('%Y-%m-%d')
    r = requests.get('https://api.open-meteo.com/v1/forecast', params={
        'latitude': -24.26,
        'longitude': -65.21,
        'daily': 'weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max',
        'timezone': 'America/Argentina/Jujuy',
        'forecast_days': 1,
    }, timeout=30)
    r.raise_for_status()
    d = r.json()['daily']
    codigo = d['weather_code'][0]
    icono, cielo = main.descripcion_clima(codigo)
    minima = round(d['temperature_2m_min'][0])
    maxima = round(d['temperature_2m_max'][0])
    lluvia = d['precipitation_probability_max'][0]
    texto_fecha = main.DIAS[ahora.weekday()] + ' ' + str(ahora.day) + ' de ' + main.MESES[ahora.month - 1]
    llueve = codigo >= 51 or (lluvia is not None and lluvia >= 60)
    seccion = 'clima_lluvia' if (llueve and main.fotos_de('clima_lluvia')) else 'clima'
    if prueba:
        ruta = '/tmp/clima-prueba.jpg'
        nueva = False
        crear_placa_clima(minima, maxima, cielo, lluvia, codigo, texto_fecha, seccion, ruta)
    else:
        ruta = 'assets/placas/' + fecha + '-clima.jpg'
        nueva = not os.path.exists(ruta)
        if nueva:
            crear_placa_clima(minima, maxima, cielo, lluvia, codigo, texto_fecha, seccion, ruta)
    lineas = [
        icono + ' Buenos días, Palpalá. Así viene el tiempo hoy, ' + texto_fecha + ':',
        '',
        '🌡️ Mínima ' + str(minima) + '° · Máxima ' + str(maxima) + '°',
        'Cielo ' + cielo,
    ]
    if lluvia is not None:
        lineas.append('☔ Probabilidad de lluvia: ' + str(lluvia) + '%')
    copia = NL.join(lineas + ['', '📰 La Mancha Digital · ' + main.LEMA,
                              '👉 Pronóstico de 7 días: ' + main.SITIO + '/clima/'])
    if nueva:
        e.setdefault('cola_redes', []).append({
            'titulo': 'El tiempo en Palpalá: ' + texto_fecha,
            'tipo': 'foto',
            'url': main.SITIO + '/clima/',
            'imagen': '/' + ruta,
            'copy_facebook': NL.join(lineas),
            'copy_instagram': NL.join(lineas + ['', 'Pronóstico de 7 días en nuestra web.']),
            'hashtags': ['#Palpalá', '#Jujuy', '#ElTiempo', '#Clima', '#LaManchaDigital'],
            'hecho': {},
            'intentos': 0,
        })
    elif not prueba:
        print('El clima de hoy ya estaba creado: no se vuelve a publicar en redes.')
    if prueba:
        aviso = '🧪 PRUEBA del clima: esta imagen no se publicó en ninguna red.'
    else:
        aviso = '☀️ Clima de la mañana listo. Guardá la imagen siguiente y copiá su texto para pegarlo en tu canal de WhatsApp.'
    main.tg('sendMessage', chat_id=main.CHAT, text=aviso)
    tg_foto(ruta, copia)
    print('Clima preparado.')


def titulos_de_hoy(fecha):
    titulos = []
    if os.path.isdir('_posts'):
        for nombre in sorted(os.listdir('_posts')):
            if not nombre.startswith(fecha) or 'resumen-del-dia' in nombre:
                continue
            t = main.leer_cabecera('_posts/' + nombre).get('title')
            if t:
                titulos.append(str(t))
    return titulos


def resumen_social(e, prueba=False):
    zona = datetime.timezone(datetime.timedelta(hours=-3))
    ahora = datetime.datetime.now(zona)
    fecha = ahora.strftime('%Y-%m-%d')
    texto_fecha = main.DIAS[ahora.weekday()] + ' ' + str(ahora.day) + ' de ' + main.MESES[ahora.month - 1]
    titulos = titulos_de_hoy(fecha)
    if prueba:
        if not titulos:
            titulos = ['Título de ejemplo de una nota del día', 'Otro título de ejemplo']
        ruta = '/tmp/resumen-prueba.jpg'
        crear_placa_resumen(texto_fecha, titulos, ruta)
        main.tg('sendMessage', chat_id=main.CHAT,
                text='🧪 PRUEBA del resumen: esta imagen no se publicó en ninguna red.')
        tg_foto(ruta, 'Resumen del día: ' + texto_fecha)
        print('Prueba del resumen enviada.')
        return
    ruta_post = '_posts/' + fecha + '-resumen-del-dia.md'
    if not os.path.exists(ruta_post):
        print('No hay resumen de hoy: no se publica nada en redes.')
        return
    if e.get('resumen_redes') == fecha:
        print('El resumen de hoy ya se envió a redes.')
        return
    cab = main.leer_cabecera(ruta_post)
    titulo = str(cab.get('title', 'Resumen del día'))
    bajada = str(cab.get('bajada', ''))
    url = main.SITIO + ahora.strftime('/%Y/%m/%d/') + 'resumen-del-dia.html'
    ruta = 'assets/placas/' + fecha + '-resumen-redes.jpg'
    imagen = ''
    try:
        if not os.path.exists(ruta):
            crear_placa_resumen(texto_fecha, titulos, ruta)
        imagen = '/' + ruta
    except Exception as ex:
        print('No se pudo crear la imagen del resumen:', ex)
    puntos = ['• ' + t for t in titulos[:6]]
    fb = NL.join(['📋 Resumen del día: ' + texto_fecha, ''] + puntos + ['', 'Todas las notas, en el enlace.'])
    ig = NL.join(['📋 Resumen del día: ' + texto_fecha, ''] + puntos + ['', 'Todas las notas en nuestra web.'])
    e.setdefault('cola_redes', []).append({
        'titulo': titulo,
        'tipo': 'foto',
        'url': url,
        'imagen': imagen,
        'copy_facebook': fb,
        'copy_instagram': ig,
        'hashtags': ['#Palpalá', '#Jujuy', '#Noticias', '#ResumenDelDía', '#LaManchaDigital'],
        'hecho': {},
        'intentos': 0,
    })
    e['resumen_redes'] = fecha
    if imagen and os.path.exists(ruta):
        try:
            tg_foto(ruta, main.mensaje_whatsapp(titulo, bajada, url, '📋'))
        except Exception as ex:
            print('No se pudo enviar la imagen a Telegram:', ex)
    print('Resumen preparado para redes.')


if __name__ == '__main__':
    estado = main.cargar()
    main.USO_FONDOS.update(estado.get('fondos', {}))
    prueba = len(sys.argv) > 2 and sys.argv[2] == 'prueba'
    try:
        if sys.argv[1] == 'clima':
            clima_social(estado, prueba)
        elif sys.argv[1] == 'resumen':
            resumen_social(estado, prueba)
    finally:
        estado['fondos'] = main.USO_FONDOS
        main.guardar(estado)
