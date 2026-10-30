import os, sys, json, re, time, html, hashlib, unicodedata, datetime
from urllib.parse import urlparse, parse_qs
import requests
import feedparser
import trafilatura
from PIL import Image, ImageDraw, ImageFont, ImageOps

ESTADO = 'state.json'
CHAT = os.environ.get('TELEGRAM_CHAT_ID', '')
TG = 'https://api.telegram.org/bot' + os.environ.get('TELEGRAM_TOKEN', '')
MODELO = os.environ.get('GROQ_MODEL') or 'openai/gpt-oss-120b'
MAX_POR_CORRIDA = 5
NL = chr(10)

DUENO, REPO = os.environ.get('GITHUB_REPOSITORY', 'usuario/repo').split('/')
SITIO = 'https://' + DUENO + '.github.io'
if REPO.lower() != DUENO.lower() + '.github.io':
    SITIO += '/' + REPO

SECCIONES = ['sociedad', 'politica', 'policiales', 'deportes', 'cultura', 'economia']
NOMBRES = {
    'sociedad': 'Sociedad', 'politica': 'Política', 'policiales': 'Policiales',
    'deportes': 'Deportes', 'cultura': 'Cultura', 'economia': 'Economía',
    'resumen': 'Resumen del día',
}
COLORES = {
    'sociedad': '#0F2A43', 'politica': '#3B1F5C', 'policiales': '#6E1423',
    'deportes': '#0B5D3B', 'cultura': '#7A4A0A', 'economia': '#1B4F72',
    'resumen': '#0F2A43',
}
DIAS = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto',
         'septiembre', 'octubre', 'noviembre', 'diciembre']
ROJO = '#D7263D'
INTENSIDAD = 0.62
FUENTES = [
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
]

PROMPT = '''Sos redactor de La Mancha Digital, un diario digital de Palpalá, Jujuy, Argentina.
Escribí una nota con tus propias palabras a partir de los datos de abajo.

REGLAS:
- Usá solo hechos que estén en los datos. No inventes nombres, cifras, cargos ni citas.
- No copies frases de la fuente. Redactá con tus palabras y mencioná la fuente (según ...).
- Tono claro, cercano y neutral, en español rioplatense, sin sensacionalismo.
- Si es un hecho policial: no identifiques a menores ni a víctimas, y usá presunto o según la policía. Nunca afirmes culpabilidad.
- Si algo es dudoso o falta un dato clave, anotalo en verificar.
- El titulo tiene como máximo 90 caracteres. La bajada es una sola oración.
- El cuerpo tiene de 3 a 5 párrafos cortos, separados por una línea en blanco.

DATOS:
Título: {titulo}
Fuente: {fuente}
Texto: {texto}

Respondé SOLO con un JSON con estas claves: titulo, bajada, cuerpo, seccion, copy_facebook, copy_instagram, hashtags (lista), verificar (lista de textos).
La clave seccion debe ser exactamente una de estas: sociedad, politica, policiales, deportes, cultura, economia.
'''


def cargar():
    if os.path.exists(ESTADO):
        with open(ESTADO, encoding='utf-8') as f:
            return json.load(f)
    return {'vistos': [], 'pendientes': {}, 'offset': 0}


def guardar(e):
    e['vistos'] = e['vistos'][-1000:]
    with open(ESTADO, 'w', encoding='utf-8') as f:
        json.dump(e, f, ensure_ascii=False, indent=1)


def limpiar(t):
    return html.unescape(re.sub(r'<[^>]+>', '', t or '')).strip()


def link_real(link):
    q = parse_qs(urlparse(link).query)
    return q['url'][0] if 'url' in q else link


def slug(t):
    t = unicodedata.normalize('NFKD', t).encode('ascii', 'ignore').decode()
    t = re.sub(r'[^a-zA-Z0-9]+', '-', t).strip('-').lower()
    return t[:60].strip('-') or 'nota'


def leer_fuentes():
    items = []
    with open('fuentes.txt', encoding='utf-8') as f:
        urls = [l.strip() for l in f if l.strip() and not l.startswith('#')]
    for url in urls:
        for ent in feedparser.parse(url).entries:
            titulo = limpiar(ent.get('title'))
            resumen_txt = limpiar(ent.get('summary'))
            if 'palpal' not in (titulo + resumen_txt).lower():
                continue
            items.append({
                'id': ent.get('id') or ent.get('link'),
                'titulo': titulo,
                'resumen': resumen_txt,
                'link': link_real(ent.get('link', '')),
            })
    return items


def texto_fuente(it):
    try:
        bruto = trafilatura.fetch_url(it['link'])
        t = trafilatura.extract(bruto) if bruto else None
        if t:
            return t[:5000]
    except Exception as ex:
        print('No se pudo leer la nota original:', ex)
    return it['resumen']


def redactar(it):
    prompt = PROMPT.format(titulo=it['titulo'], fuente=it['link'], texto=texto_fuente(it))
    datos = {
        'model': MODELO,
        'messages': [{'role': 'user', 'content': prompt}],
        'response_format': {'type': 'json_object'},
    }
    cab = {'Authorization': 'Bearer ' + os.environ['GROQ_API_KEY']}
    for intento in range(3):
        r = requests.post('https://api.groq.com/openai/v1/chat/completions',
                          headers=cab, json=datos, timeout=90)
        if r.status_code == 429:
            time.sleep(30)
            continue
        break
    if not r.ok:
        print('Respuesta de Groq:', r.status_code, r.text[:500], '| Modelo usado:', MODELO)
    r.raise_for_status()
    return json.loads(r.json()['choices'][0]['message']['content'])


def tg(metodo, **datos):
    r = requests.post(f'{TG}/{metodo}', json=datos, timeout=30)
    if not r.ok:
        print('Respuesta de Telegram:', r.status_code, r.text[:300])
    r.raise_for_status()
    return r.json()['result']


def mensaje_whatsapp(titulo, bajada, url, tipo):
    return NL.join([
        '📲 Para tu canal de WhatsApp (copiá y pegá):', '',
        tipo + ' ' + titulo, '', bajada, '',
        '👉 Leé la nota completa: ' + url,
    ])


def enviar_borrador(nid, nota, fuente):
    ver = nota.get('verificar') or []
    if isinstance(ver, list):
        ver = '; '.join(map(str, ver))
    sec = str(nota.get('seccion', '')).lower().strip()
    texto = NL.join([
        '📰 ' + nota['titulo'], '', nota['bajada'], '', nota['cuerpo'], '',
        '🏷️ Sección: ' + NOMBRES.get(sec, 'Sociedad'),
        '🔗 Fuente: ' + fuente,
        '⚠️ Verificar: ' + (ver or 'nada en particular'),
    ])
    botones = [[
        {'text': '✅ Aprobar', 'callback_data': 'ok:' + nid},
        {'text': '❌ Rechazar', 'callback_data': 'no:' + nid},
    ]]
    tg('sendMessage', chat_id=CHAT, text=texto[:4000],
       disable_web_page_preview=True, reply_markup={'inline_keyboard': botones})


def fuente(tam):
    for ruta in FUENTES:
        if os.path.exists(ruta):
            return ImageFont.truetype(ruta, tam)
    return ImageFont.load_default(tam)


def elegir_fondo(seccion, titulo):
    for nombre in (seccion, 'general'):
        carpeta = 'assets/fondos/' + nombre
        if not os.path.isdir(carpeta):
            continue
        fotos = sorted(f for f in os.listdir(carpeta)
                       if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')))
        if fotos:
            n = int(hashlib.md5(titulo.encode()).hexdigest(), 16) % len(fotos)
            return carpeta + '/' + fotos[n]
    return None


def crear_placa(titulo, seccion, ruta):
    ancho, alto = 1200, 675
    color = COLORES.get(seccion, '#0F2A43')
    img = None
    fondo = elegir_fondo(seccion, titulo)
    if fondo:
        try:
            foto = ImageOps.exif_transpose(Image.open(fondo)).convert('RGB')
            foto = ImageOps.fit(foto, (ancho, alto))
            img = Image.blend(foto, Image.new('RGB', (ancho, alto), color), INTENSIDAD)
        except Exception as ex:
            print('No se pudo usar el fondo:', fondo, ex)
            fondo = None
    if img is None:
        img = Image.new('RGB', (ancho, alto), color)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 28, alto], fill=ROJO)
    d.rectangle([0, alto - 100, ancho, alto], fill='#0A1B2C')
    etiqueta = NOMBRES.get(seccion, 'Sociedad').upper()
    f_et = fuente(30)
    w_et = d.textlength(etiqueta, font=f_et)
    d.rectangle([70, 55, 70 + w_et + 36, 110], fill=ROJO)
    d.text((88, 62), etiqueta, font=f_et, fill='white')
    if fondo:
        ilus = 'IMAGEN ILUSTRATIVA'
        f_ilus = fuente(20)
        d.text((ancho - 70 - d.textlength(ilus, font=f_ilus), 72), ilus,
               font=f_ilus, fill='#DDE3EA')
    f_tit = fuente(58)
    lineas, linea = [], ''
    for palabra in titulo.split():
        prueba = (linea + ' ' + palabra).strip()
        if d.textlength(prueba, font=f_tit) <= ancho - 150:
            linea = prueba
        else:
            if linea:
                lineas.append(linea)
            linea = palabra
    if linea:
        lineas.append(linea)
    if len(lineas) > 5:
        lineas = lineas[:5]
        lineas[-1] = lineas[-1] + '...'
    y = 150
    for texto in lineas:
        d.text((70, y), texto, font=f_tit, fill='white')
        y += 75
    d.text((70, alto - 68), 'LA MANCHA DIGITAL', font=fuente(34), fill='white')
    lugar = 'Palpalá, Jujuy'
    f_lugar = fuente(28)
    d.text((ancho - 70 - d.textlength(lugar, font=f_lugar), alto - 64),
           lugar, font=f_lugar, fill='#B8C4D0')
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    img.save(ruta, quality=88)


def publicar_sitio(nota, fuente_url):
    zona = datetime.timezone(datetime.timedelta(hours=-3))
    ahora = datetime.datetime.now(zona)
    fecha = ahora.strftime('%Y-%m-%d')
    corto = slug(nota['titulo']) + '-' + hashlib.md5(fuente_url.encode()).hexdigest()[:4]
    seccion = str(nota.get('seccion', '')).lower().strip()
    if seccion not in SECCIONES:
        seccion = 'sociedad'
    imagen = ''
    try:
        ruta_img = 'assets/placas/' + fecha + '-' + corto + '.jpg'
        crear_placa(nota['titulo'], seccion, ruta_img)
        imagen = '/' + ruta_img
    except Exception as ex:
        print('No se pudo crear la imagen:', ex)
    bajada = nota['bajada'].strip()
    lineas = [
        '---',
        'layout: post',
        'title: ' + json.dumps(nota['titulo'], ensure_ascii=False),
        'bajada: ' + json.dumps(bajada, ensure_ascii=False),
        'description: ' + json.dumps(bajada, ensure_ascii=False),
        'seccion: ' + seccion,
        'seccion_nombre: ' + NOMBRES[seccion],
        'date: ' + ahora.strftime('%Y-%m-%d %H:%M:%S') + ' -0300',
    ]
    if imagen:
        lineas.append('image: ' + imagen)
    lineas += ['---', '']
    for p in nota['cuerpo'].splitlines():
        if p.strip():
            lineas += [p.strip(), '']
    lineas.append('*Fuente: [' + urlparse(fuente_url).netloc + '](' + fuente_url + ')*')
    os.makedirs('_posts', exist_ok=True)
    with open('_posts/' + fecha + '-' + corto + '.md', 'w', encoding='utf-8') as f:
        f.write(NL.join(lineas) + NL)
    return SITIO + ahora.strftime('/%Y/%m/%d/') + corto + '.html'


def leer_cabecera(ruta):
    with open(ruta, encoding='utf-8') as f:
        lineas = f.read().splitlines()
    datos = {}
    if not lineas or lineas[0].strip() != '---':
        return datos
    for linea in lineas[1:]:
        if linea.strip() == '---':
            break
        if ':' not in linea:
            continue
        clave, valor = linea.split(':', 1)
        valor = valor.strip()
        if valor.startswith(chr(34)):
            try:
                valor = json.loads(valor)
            except Exception:
                pass
        datos[clave.strip()] = valor
    return datos


def resumen(e):
    zona = datetime.timezone(datetime.timedelta(hours=-3))
    ahora = datetime.datetime.now(zona)
    fecha = ahora.strftime('%Y-%m-%d')
    destino = '_posts/' + fecha + '-resumen-del-dia.md'
    if os.path.exists(destino):
        print('El resumen de hoy ya existe.')
        return
    grupos = {}
    if os.path.isdir('_posts'):
        for nombre in sorted(os.listdir('_posts')):
            if not nombre.startswith(fecha) or not nombre.endswith('.md'):
                continue
            if 'resumen-del-dia' in nombre:
                continue
            d = leer_cabecera('_posts/' + nombre)
            if not d.get('title'):
                continue
            sec = d.get('seccion', 'sociedad')
            if sec not in SECCIONES:
                sec = 'sociedad'
            url = SITIO + ahora.strftime('/%Y/%m/%d/') + nombre[11:-3] + '.html'
            grupos.setdefault(sec, []).append((d['title'], d.get('bajada', ''), url))
    total = sum(len(v) for v in grupos.values())
    if total == 0:
        print('Hoy no se publicaron notas: no se crea el resumen.')
        return
    texto_fecha = DIAS[ahora.weekday()] + ' ' + str(ahora.day) + ' de ' + MESES[ahora.month - 1]
    titulo = 'Resumen del día: noticias de Palpalá, Jujuy y Argentina (' + texto_fecha + ')'
    if total == 1:
        bajada = '1 nota del día sobre Palpalá, Jujuy y Argentina.'
    else:
        bajada = str(total) + ' notas del día sobre Palpalá, Jujuy y Argentina.'
    cuerpo = ['Estas fueron las noticias del día sobre Palpalá, Jujuy y Argentina que publicamos hoy en La Mancha Digital:', '']
    for sec in SECCIONES:
        if sec not in grupos:
            continue
        cuerpo += ['**' + NOMBRES[sec] + '**', '']
        for t, b, u in grupos[sec]:
            t = t.replace('[', '(').replace(']', ')')
            item = '- [' + t + '](' + u + ')'
            if b:
                item += ': ' + b
            cuerpo.append(item)
        cuerpo.append('')
    imagen = ''
    try:
        ruta_img = 'assets/placas/' + fecha + '-resumen-del-dia.jpg'
        crear_placa(titulo, 'resumen', ruta_img)
        imagen = '/' + ruta_img
    except Exception as ex:
        print('No se pudo crear la imagen:', ex)
    cab = [
        '---',
        'layout: post',
        'title: ' + json.dumps(titulo, ensure_ascii=False),
        'bajada: ' + json.dumps(bajada, ensure_ascii=False),
        'description: ' + json.dumps(bajada, ensure_ascii=False),
        'seccion: resumen',
        'seccion_nombre: Resumen del día',
        'date: ' + ahora.strftime('%Y-%m-%d %H:%M:%S') + ' -0300',
    ]
    if imagen:
        cab.append('image: ' + imagen)
    cab += ['---', '']
    with open(destino, 'w', encoding='utf-8') as f:
        f.write(NL.join(cab + cuerpo) + NL)
    url = SITIO + ahora.strftime('/%Y/%m/%d/') + 'resumen-del-dia.html'
    print('Resumen creado con', total, 'notas.')
    try:
        tg('sendMessage', chat_id=CHAT,
           text='📋 Resumen del día publicado. En 1 a 3 minutos estará en: ' + url)
        tg('sendMessage', chat_id=CHAT, text=mensaje_whatsapp(titulo, bajada, url, '📋'))
    except Exception as ex:
        print('No se pudo avisar por Telegram:', ex)


def buscar(e):
    nuevos = 0
    items = leer_fuentes()
    print('Notas encontradas en las fuentes:', len(items))
    print('Modelo configurado:', MODELO)
    for it in items:
        if it['id'] in e['vistos']:
            continue
        if nuevos >= MAX_POR_CORRIDA:
            break
        try:
            nota = redactar(it)
            nid = hashlib.md5(it['id'].encode()).hexdigest()[:10]
            e['pendientes'][nid] = {'nota': nota, 'fuente': it['link']}
            enviar_borrador(nid, nota, it['link'])
            e['vistos'].append(it['id'])
            nuevos += 1
        except Exception as ex:
            print('Error con una nota:', ex)
        time.sleep(15)
    print('Borradores enviados:', nuevos)


def aprobar(e):
    ups = tg('getUpdates', offset=e['offset'], timeout=0, allowed_updates=['callback_query'])
    for u in ups:
        e['offset'] = u['update_id'] + 1
        cb = u.get('callback_query')
        if not cb or str(cb['from']['id']) != CHAT:
            continue
        try:
            tg('answerCallbackQuery', callback_query_id=cb['id'])
        except Exception:
            pass
        accion, nid = cb['data'].split(':', 1)
        item = e['pendientes'].get(nid)
        if not item:
            tg('sendMessage', chat_id=CHAT, text='Esa nota ya fue procesada.')
            continue
        if accion == 'no':
            del e['pendientes'][nid]
            tg('sendMessage', chat_id=CHAT, text='Nota descartada.')
            continue
        try:
            url = publicar_sitio(item['nota'], item['fuente'])
            del e['pendientes'][nid]
            tg('sendMessage', chat_id=CHAT,
               text='✅ Aprobada. En 1 a 3 minutos estará en: ' + url)
        except Exception as ex:
            tg('sendMessage', chat_id=CHAT, text='Error al publicar: ' + str(ex)[:300])
            continue
        try:
            tg('sendMessage', chat_id=CHAT,
               text=mensaje_whatsapp(item['nota']['titulo'], item['nota']['bajada'], url, '📰'))
        except Exception as ex:
            print('No se pudo enviar el mensaje para WhatsApp:', ex)


if __name__ == '__main__':
    estado = cargar()
    try:
        if sys.argv[1] == 'buscar':
            buscar(estado)
        elif sys.argv[1] == 'aprobar':
            aprobar(estado)
        elif sys.argv[1] == 'resumen':
            resumen(estado)
    finally:
        guardar(estado)
