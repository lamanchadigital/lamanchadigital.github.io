import os, json, time
import requests

GRAPH = 'https://graph.facebook.com'
if os.environ.get('META_VERSION'):
    GRAPH += '/' + os.environ['META_VERSION']
PAGE_ID = os.environ.get('FB_PAGE_ID', '')
TOKEN = os.environ.get('FB_PAGE_TOKEN', '')
IG_ID = os.environ.get('IG_USER_ID', '')
NL = chr(10)
MAX_INTENTOS = 3
MAX_ESPERAS = 10


def meta(metodo, ruta, **datos):
    datos['access_token'] = TOKEN
    if metodo == 'GET':
        r = requests.get(GRAPH + '/' + ruta, params=datos, timeout=60)
    else:
        r = requests.post(GRAPH + '/' + ruta, data=datos, timeout=60)
    if not r.ok:
        raise Exception('Meta ' + str(r.status_code) + ': ' + r.text[:300])
    return r.json()


def etiquetas(lista):
    salida = []
    for h in lista[:10]:
        h = ''.join(str(h).split())
        if not h:
            continue
        salida.append(h if h.startswith('#') else '#' + h)
    return ' '.join(salida)


def con_enlace(it):
    texto = it['copy_facebook']
    if it.get('url'):
        texto = NL.join([texto, '', '👉 ' + it['url']])
    return texto


def publicar_facebook(it, sitio):
    if it.get('tipo') == 'video' and it.get('video'):
        r = meta('POST', PAGE_ID + '/videos', file_url=sitio + it['video'], description=con_enlace(it))
    elif it.get('imagenes'):
        imagenes = it['imagenes']
        if len(imagenes) == 1:
            r = meta('POST', PAGE_ID + '/photos', url=sitio + imagenes[0], caption=con_enlace(it))
        else:
            datos = {'message': con_enlace(it)}
            for i, ruta in enumerate(imagenes[:10]):
                foto = meta('POST', PAGE_ID + '/photos', url=sitio + ruta, published='false')
                datos['attached_media[' + str(i) + ']'] = json.dumps({'media_fbid': foto['id']})
            r = meta('POST', PAGE_ID + '/feed', **datos)
    elif it.get('tipo') == 'foto' and it.get('imagen'):
        r = meta('POST', PAGE_ID + '/photos', url=sitio + it['imagen'], caption=con_enlace(it))
    else:
        r = meta('POST', PAGE_ID + '/feed', message=it['copy_facebook'], link=it['url'])
    return r.get('id', '')


def publicar_instagram(it, sitio):
    imagen = it.get('imagen_ig') or it.get('imagen')
    if not imagen:
        raise Exception('no hay imagen para Instagram')
    web = sitio.replace('https://', '')
    partes = [it['copy_instagram'], '']
    if it.get('tipo') == 'foto':
        partes += ['🔗 Más información en la web: link en la bio (' + web + ')', '']
    elif it.get('url'):
        partes += ['🔗 Nota completa: link en la bio (' + web + ')', '']
    partes.append(etiquetas(it.get('hashtags') or []))
    texto = NL.join(partes)
    cont = meta('POST', IG_ID + '/media', image_url=sitio + imagen, caption=texto[:2200])
    cid = cont['id']
    for intento in range(12):
        estado = meta('GET', cid, fields='status_code').get('status_code')
        if estado in (None, 'FINISHED'):
            break
        if estado in ('ERROR', 'EXPIRED'):
            raise Exception('Instagram no pudo procesar la imagen (' + str(estado) + ')')
        time.sleep(5)
    else:
        raise Exception('Instagram tardó demasiado en procesar la imagen')
    r = meta('POST', IG_ID + '/media_publish', creation_id=cid)
    return r.get('id', '')


def existe(url):
    try:
        r = requests.head(url + '?c=' + str(int(time.time())), timeout=20, allow_redirects=True)
        return r.status_code == 200
    except Exception:
        return False


def listo_en_sitio(it, sitio):
    rutas = []
    if it.get('video'):
        rutas.append(it['video'])
    rutas += it.get('imagenes') or []
    for clave in ('imagen', 'imagen_ig'):
        if it.get(clave):
            rutas.append(it[clave])
    urls = [sitio + r for r in rutas]
    if it.get('url'):
        urls.append(it['url'])
    return all(existe(u) for u in urls)


def esperar_sitio(it, sitio):
    for intento in range(5):
        if listo_en_sitio(it, sitio):
            return True
        time.sleep(15)
    return False


def avisar(enviar, chat, texto):
    try:
        enviar('sendMessage', chat_id=chat, text=texto[:4000])
    except Exception as ex:
        print('No se pudo avisar por Telegram:', ex)


def procesar(e, enviar, sitio, chat):
    cola = e.get('cola_redes', [])
    if not cola:
        print('No hay notas para publicar en redes.')
        return
    print('Notas en la cola de redes:', len(cola))
    time.sleep(20)
    quedan = []
    for it in cola:
        if not esperar_sitio(it, sitio):
            it['esperas'] = it.get('esperas', 0) + 1
            if it['esperas'] < MAX_ESPERAS:
                quedan.append(it)
                if it['esperas'] == 1:
                    avisar(enviar, chat, '⏳ Redes: ' + it['titulo'] + NL +
                           'El sitio todavía no tiene los archivos. Se reintenta solo en unos minutos.')
            else:
                avisar(enviar, chat, '⚠️ Redes: ' + it['titulo'] + NL +
                       'No se publicó: el sitio no tuvo los archivos a tiempo. Revisá en GitHub que Publicar sitio esté en verde.')
            continue
        hecho = it.setdefault('hecho', {})
        it['intentos'] = it.get('intentos', 0) + 1
        partes = []
        if not hecho.get('fb'):
            if PAGE_ID and TOKEN:
                try:
                    publicar_facebook(it, sitio)
                    hecho['fb'] = True
                    partes.append('Facebook ✅')
                except Exception as ex:
                    partes.append('Facebook ❌ ' + str(ex)[:250])
            else:
                hecho['fb'] = True
                partes.append('Facebook: sin configurar')
        if not hecho.get('ig'):
            if it.get('sin_ig'):
                hecho['ig'] = True
                partes.append('Instagram: no aplica para videos por ahora')
            elif IG_ID and TOKEN:
                try:
                    publicar_instagram(it, sitio)
                    hecho['ig'] = True
                    partes.append('Instagram ✅')
                except Exception as ex:
                    if '2207051' in str(ex):
                        hecho['ig'] = True
                        partes.append('Instagram ⏸ bloqueado por Instagram (antispam). No se reintenta.')
                    else:
                        partes.append('Instagram ❌ ' + str(ex)[:250])
            else:
                hecho['ig'] = True
                partes.append('Instagram: sin configurar')
        falta = not (hecho.get('fb') and hecho.get('ig'))
        aviso = '📣 Redes: ' + it['titulo'] + NL + ' · '.join(partes)
        if falta and it['intentos'] < MAX_INTENTOS:
            aviso += NL + '↻ Se reintenta en la próxima publicación.'
            quedan.append(it)
        elif falta:
            aviso += NL + '⚠️ Se dejó de reintentar. Si querés, publicalo a mano.'
        avisar(enviar, chat, aviso)
        time.sleep(10)
    e['cola_redes'] = quedan
