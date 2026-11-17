import os, sys, json, time, datetime, hashlib, unicodedata, re
import requests
from PIL import Image, ImageOps

TOKEN = os.environ.get('TELEGRAM_TOKEN', '')
NL = chr(10)
SECCIONES = {
    'sociedad': 'Sociedad', 'politica': 'Política', 'policiales': 'Policiales',
    'deportes': 'Deportes', 'cultura': 'Cultura', 'economia': 'Economía',
}
MAX_VIDEO = 20 * 1024 * 1024
DIAS_FOTOS = 180
DIAS_VIDEOS = 90
AYUDA = NL.join([
    '📝 Cómo publicar una nota propia',
    '',
    'No hace falta escribir /ayuda cada vez: mandá directamente la foto o el video con el texto.',
    '',
    '1) Mandame una o varias FOTOS (como foto, no como archivo) o un VIDEO (hasta 20 MB), con el texto en el pie de foto.',
    '2) Primera línea: el título. Después, el texto. Dejá una línea en blanco entre párrafos.',
    '3) Opcional: una línea con la sección: #sociedad #politica #policiales #deportes #cultura #economia.',
    '4) Para publicar sin vista previa, poné un ! al principio del título.',
    '5) Para una nota solo de texto, escribí /nota y a continuación el título y el texto.',
])


def zona():
    return datetime.timezone(datetime.timedelta(hours=-3))


def slug(t):
    t = unicodedata.normalize('NFKD', t).encode('ascii', 'ignore').decode()
    t = re.sub(r'[^a-zA-Z0-9]+', '-', t).strip('-').lower()
    return t[:60].strip('-') or 'nota'


def interpretar(texto):
    seccion = 'sociedad'
    resto = []
    for linea in (texto or '').splitlines():
        s = linea.strip().lower()
        if s.startswith('#') and s[1:] in SECCIONES:
            seccion = s[1:]
        else:
            resto.append(linea.rstrip())
    while resto and not resto[0].strip():
        resto.pop(0)
    if not resto:
        return None
    titulo = resto[0].strip()
    directo = titulo.startswith('!')
    titulo = titulo.lstrip('!').strip()
    cuerpo = NL.join(resto[1:]).strip()
    if not titulo:
        return None
    return {'titulo': titulo, 'cuerpo': cuerpo, 'seccion': seccion, 'directo': directo}


def seguro(texto):
    return texto.replace('{%', '{ %').replace('{{', '{ {')


def bajada_de(titulo, cuerpo):
    primero = cuerpo.split(NL + NL)[0].replace(NL, ' ').strip() if cuerpo else ''
    if not primero:
        return titulo
    if len(primero) > 170:
        primero = primero[:167].rstrip() + '...'
    return primero


def recortar_parrafos(texto, limite):
    if len(texto) <= limite:
        return texto
    corte = texto[:limite]
    punto = max(corte.rfind(NL + NL), corte.rfind('. '))
    if punto > limite // 2:
        corte = corte[:punto + 1]
    return corte.rstrip() + '…'


def descargar(tg, file_id, base, ext_por_defecto):
    info = tg('getFile', file_id=file_id)
    ext = os.path.splitext(info['file_path'])[1].lower() or ext_por_defecto
    destino = base + ext
    r = requests.get('https://api.telegram.org/file/bot' + TOKEN + '/' + info['file_path'], timeout=180)
    r.raise_for_status()
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    with open(destino, 'wb') as f:
        f.write(r.content)
    return destino


def ajustar_ig(origen, destino):
    img = ImageOps.exif_transpose(Image.open(origen)).convert('RGB')
    w, h = img.size
    ratio = w / h
    if ratio < 0.8:
        nuevo_h = int(w / 0.8)
        arriba = int((h - nuevo_h) * 0.3)
        img = img.crop((0, arriba, w, arriba + nuevo_h))
    elif ratio > 1.91:
        nuevo_w = int(h * 1.91)
        izq = (w - nuevo_w) // 2
        img = img.crop((izq, 0, izq + nuevo_w, h))
    img.save(destino, quality=90)


def publicar(e, b, tg, chat, sitio, crear_placa):
    ahora = datetime.datetime.now(zona())
    fecha = ahora.strftime('%Y-%m-%d')
    titulo = b['titulo']
    seccion = b['seccion']
    cuerpo = seguro(b['cuerpo'])
    base = fecha + '-' + slug(titulo) + '-' + hashlib.md5((titulo + str(time.time())).encode()).hexdigest()[:4]
    fotos = []
    for i, fid in enumerate(b['fotos'], start=1):
        fotos.append(descargar(tg, fid, 'assets/fotos/' + base + '-' + str(i), '.jpg'))
    video = ''
    if b['video']:
        video = descargar(tg, b['video'], 'assets/videos/' + base, '.mp4')
    if fotos:
        imagen = fotos[0]
        imagen_ig = 'assets/fotos/' + base + '-ig.jpg'
        ajustar_ig(fotos[0], imagen_ig)
    else:
        imagen = 'assets/placas/' + base + '.jpg'
        crear_placa(titulo, seccion, imagen)
        imagen_ig = imagen
    bajada = bajada_de(titulo, cuerpo)
    lineas = [
        '---',
        'layout: post',
        'title: ' + json.dumps(titulo, ensure_ascii=False),
        'bajada: ' + json.dumps(bajada, ensure_ascii=False),
        'description: ' + json.dumps(bajada, ensure_ascii=False),
        'seccion: ' + seccion,
        'seccion_nombre: ' + SECCIONES[seccion],
        'date: ' + ahora.strftime('%Y-%m-%d %H:%M:%S') + ' -0300',
        'image: /' + imagen,
        '---',
        '',
    ]
    if cuerpo:
        lineas += [cuerpo, '']
    for ruta in fotos[1:]:
        lineas += ['![Foto](' + sitio + '/' + ruta + ')', '']
    if video:
        lineas += [
            '<video controls preload=metadata playsinline style=width:100%;max-height:75vh poster=' + sitio + '/' + imagen + '>',
            '<source src=' + sitio + '/' + video + ' type=video/mp4></video>',
            '',
        ]
    lineas.append('*Redacción de La Mancha Digital*')
    os.makedirs('_posts', exist_ok=True)
    with open('_posts/' + base + '.md', 'w', encoding='utf-8') as f:
        f.write(NL.join(lineas) + NL)
    url = sitio + ahora.strftime('/%Y/%m/%d/') + base[11:] + '.html'
    texto_social = titulo + ((NL + NL + b['cuerpo']) if b['cuerpo'] else '')
    etiquetas = ['#Palpalá', '#Jujuy', '#' + SECCIONES[seccion], '#LaManchaDigital']
    item = {
        'titulo': titulo,
        'url': url,
        'imagen': '/' + imagen,
        'imagen_ig': '/' + imagen_ig,
        'copy_facebook': texto_social[:5000],
        'copy_instagram': recortar_parrafos(texto_social, 1700),
        'hashtags': etiquetas,
        'hecho': {},
        'intentos': 0,
    }
    if video:
        item['tipo'] = 'video'
        item['video'] = '/' + video
        item['sin_ig'] = True
    e.setdefault('cola_redes', []).append(item)
    tg('sendMessage', chat_id=chat, text='✅ Publicada. En 1 a 3 minutos estará en: ' + url)
    partes = ['📲 Para tu canal de WhatsApp (copiá y pegá):', '', '📰 ' + titulo, '']
    if b['cuerpo']:
        partes += [recortar_parrafos(b['cuerpo'], 1500), '']
    partes.append('👉 Leé la nota completa: ' + url)
    tg('sendMessage', chat_id=chat, text=NL.join(partes))


def atender_grupo(e, msgs, tg, chat, sitio, crear_placa):
    texto = ''
    fotos = []
    video = None
    for m in msgs:
        t = m.get('caption') or m.get('text') or ''
        if t and not texto:
            texto = t
        if m.get('photo'):
            fotos.append(m['photo'][-1]['file_id'])
        if m.get('video'):
            video = m['video']
    if not fotos and not video:
        primero = (msgs[0].get('text') or '').strip()
        bajo = primero.lower()
        if bajo in ('/start', '/ayuda', '/help'):
            tg('sendMessage', chat_id=chat, text=AYUDA)
            return
        if not bajo.startswith('/nota'):
            return
        texto = primero[5:].strip()
    datos = interpretar(texto)
    if not datos:
        tg('sendMessage', chat_id=chat,
           text='Falta el texto. Enviá la foto o el video con un pie de foto: primera línea el título y después el contenido.')
        return
    if video and video.get('file_size', 0) > MAX_VIDEO:
        tg('sendMessage', chat_id=chat,
           text='El video pesa más de 20 MB y no lo puedo descargar. Enviá uno más corto o más liviano.')
        return
    borrador = {
        'titulo': datos['titulo'],
        'cuerpo': datos['cuerpo'],
        'seccion': datos['seccion'],
        'fotos': fotos[:10],
        'video': video['file_id'] if video else '',
    }
    if datos['directo']:
        publicar(e, borrador, tg, chat, sitio, crear_placa)
        return
    nid = hashlib.md5((datos['titulo'] + str(time.time())).encode()).hexdigest()[:8]
    manuales = e.setdefault('manuales', {})
    manuales[nid] = borrador
    if len(manuales) > 30:
        for k in list(manuales)[:len(manuales) - 30]:
            del manuales[k]
    detalle = str(len(borrador['fotos'])) + ' foto(s)' + (' · 1 video' if video else '')
    vista = NL.join([
        '📝 Nota propia lista para publicar', '',
        '📰 ' + datos['titulo'], '',
        datos['cuerpo'][:3300], '',
        '🏷️ Sección: ' + SECCIONES[datos['seccion']],
        '🖼️ ' + detalle,
    ])
    botones = {'inline_keyboard': [[
        {'text': '✅ Publicar', 'callback_data': 'mp:' + nid},
        {'text': '❌ Descartar', 'callback_data': 'mn:' + nid},
    ]]}
    if borrador['fotos']:
        tg('sendPhoto', chat_id=chat, photo=borrador['fotos'][0], caption=datos['titulo'][:200])
    elif video:
        tg('sendVideo', chat_id=chat, video=video['file_id'], caption=datos['titulo'][:200])
    tg('sendMessage', chat_id=chat, text=vista[:4000], reply_markup=botones)


def mensajes(e, ups, tg, chat, sitio, crear_placa):
    grupos = {}
    orden = []
    for u in ups:
        m = u.get('message')
        if not m or str(m.get('chat', {}).get('id')) != str(chat):
            continue
        clave = m.get('media_group_id') or ('m' + str(m['message_id']))
        if clave not in grupos:
            grupos[clave] = []
            orden.append(clave)
        grupos[clave].append(m)
    for clave in orden:
        try:
            atender_grupo(e, grupos[clave], tg, chat, sitio, crear_placa)
        except Exception as ex:
            print('Error con un mensaje propio:', ex)
            try:
                tg('sendMessage', chat_id=chat, text='No pude procesar tu mensaje: ' + str(ex)[:300])
            except Exception:
                pass


def decidir_redes(e, accion, nid, tg, chat):
    pendientes = e.get('pendientes_redes', {})
    item = pendientes.get(nid)
    if not item:
        tg('sendMessage', chat_id=chat, text='Eso ya fue procesado.')
        return
    del pendientes[nid]
    if accion == 'rn':
        tg('sendMessage', chat_id=chat, text='Listo: no se publica en redes.')
        return
    e.setdefault('cola_redes', []).append(item)
    tg('sendMessage', chat_id=chat, text='✅ Va a salir en Facebook e Instagram en unos minutos.')


def callback(e, u, tg, chat, sitio, crear_placa):
    cb = u.get('callback_query')
    datos = str(cb.get('data', '')) if cb else ''
    if not datos.startswith(('mp:', 'mn:', 'rp:', 'rn:')):
        return False
    if str(cb['from']['id']) != str(chat):
        return True
    try:
        tg('answerCallbackQuery', callback_query_id=cb['id'])
    except Exception:
        pass
    accion, nid = datos.split(':', 1)
    if accion in ('rp', 'rn'):
        decidir_redes(e, accion, nid, tg, chat)
        return True
    borrador = e.get('manuales', {}).get(nid)
    if not borrador:
        tg('sendMessage', chat_id=chat, text='Esa nota ya fue procesada.')
        return True
    if accion == 'mn':
        del e['manuales'][nid]
        tg('sendMessage', chat_id=chat, text='Nota descartada.')
        return True
    try:
        publicar(e, borrador, tg, chat, sitio, crear_placa)
        del e['manuales'][nid]
    except Exception as ex:
        tg('sendMessage', chat_id=chat, text='Error al publicar tu nota: ' + str(ex)[:300])
    return True


def limpiar():
    ahora = datetime.datetime.now(zona())
    borrados = 0
    for carpeta, dias in (('assets/fotos', DIAS_FOTOS), ('assets/videos', DIAS_VIDEOS)):
        if not os.path.isdir(carpeta):
            continue
        limite = (ahora - datetime.timedelta(days=dias)).strftime('%Y-%m-%d')
        for nombre in os.listdir(carpeta):
            if len(nombre) > 10 and nombre[:4].isdigit() and nombre[4] == '-' and nombre[7] == '-' and nombre[:10] < limite:
                os.remove(carpeta + '/' + nombre)
                borrados += 1
    print('Archivos propios antiguos borrados:', borrados)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'limpiar':
        limpiar()
