import os, time
import requests

GRAPH = 'https://graph.facebook.com'
if os.environ.get('META_VERSION'):
    GRAPH += '/' + os.environ['META_VERSION']
PAGE_ID = os.environ.get('FB_PAGE_ID', '')
TOKEN = os.environ.get('FB_PAGE_TOKEN', '')
IG_ID = os.environ.get('IG_USER_ID', '')
NL = chr(10)
MAX_INTENTOS = 3


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


def publicar_facebook(it):
    r = meta('POST', PAGE_ID + '/feed', message=it['copy_facebook'], link=it['url'])
    return r.get('id', '')


def publicar_instagram(it, sitio):
    if not it.get('imagen'):
        raise Exception('la nota no tiene imagen')
    texto = NL.join([
        it['copy_instagram'], '',
        '🔗 Nota completa: link en la bio (' + sitio.replace('https://', '') + ')', '',
        etiquetas(it.get('hashtags') or []),
    ])
    cont = meta('POST', IG_ID + '/media', image_url=sitio + it['imagen'], caption=texto[:2200])
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


def procesar(e, enviar, sitio, chat):
    cola = e.get('cola_redes', [])
    if not cola:
        print('No hay notas para publicar en redes.')
        return
    print('Notas en la cola de redes:', len(cola))
    time.sleep(20)
    quedan = []
    for it in cola:
        hecho = it.setdefault('hecho', {})
        it['intentos'] = it.get('intentos', 0) + 1
        partes = []
        if not hecho.get('fb'):
            if PAGE_ID and TOKEN:
                try:
                    publicar_facebook(it)
                    hecho['fb'] = True
                    partes.append('Facebook ✅')
                except Exception as ex:
                    partes.append('Facebook ❌ ' + str(ex)[:250])
            else:
                hecho['fb'] = True
                partes.append('Facebook: sin configurar')
        if not hecho.get('ig'):
            if IG_ID and TOKEN:
                try:
                    publicar_instagram(it, sitio)
                    hecho['ig'] = True
                    partes.append('Instagram ✅')
                except Exception as ex:
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
        try:
            enviar('sendMessage', chat_id=chat, text=aviso[:4000])
        except Exception as ex:
            print('No se pudo avisar por Telegram:', ex)
        time.sleep(10)
    e['cola_redes'] = quedan
