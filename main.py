import os, sys, json, re, time, html, hashlib, unicodedata, datetime
from urllib.parse import urlparse, parse_qs
import requests
import feedparser
import trafilatura

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

PROMPT = '''Sos redactor de La Mancha Digital, un diario digital de Palpalá, Jujuy, Argentina.
Escribí una nota con tus propias palabras a partir de los datos de abajo.

REGLAS:
- Usá solo hechos que estén en los datos. No inventes nombres, cifras, cargos ni citas.
- No copies frases de la fuente. Redactá con tus palabras y mencioná la fuente (según ...).
- Tono claro, cercano y neutral, en español rioplatense, sin sensacionalismo.
- Si es un hecho policial: no identifiques a menores ni a víctimas, y usá presunto o según la policía. Nunca afirmes culpabilidad.
- Si algo es dudoso o falta un dato clave, anotalo en verificar.
- El cuerpo tiene de 3 a 5 párrafos cortos, separados por una línea en blanco.

DATOS:
Título: {titulo}
Fuente: {fuente}
Texto: {texto}

Respondé SOLO con un JSON con estas claves: titulo, bajada, cuerpo, copy_facebook, copy_instagram, hashtags (lista), verificar (lista de textos).
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
            resumen = limpiar(ent.get('summary'))
            if 'palpal' not in (titulo + resumen).lower():
                continue
            items.append({
                'id': ent.get('id') or ent.get('link'),
                'titulo': titulo,
                'resumen': resumen,
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


def enviar_borrador(nid, nota, fuente):
    ver = nota.get('verificar') or []
    if isinstance(ver, list):
        ver = '; '.join(map(str, ver))
    texto = NL.join([
        '📰 ' + nota['titulo'], '', nota['bajada'], '', nota['cuerpo'], '',
        '🔗 Fuente: ' + fuente,
        '⚠️ Verificar: ' + (ver or 'nada en particular'),
    ])
    botones = [[
        {'text': '✅ Aprobar', 'callback_data': 'ok:' + nid},
        {'text': '❌ Rechazar', 'callback_data': 'no:' + nid},
    ]]
    tg('sendMessage', chat_id=CHAT, text=texto[:4000],
       disable_web_page_preview=True, reply_markup={'inline_keyboard': botones})


def publicar_sitio(nota, fuente):
    zona = datetime.timezone(datetime.timedelta(hours=-3))
    ahora = datetime.datetime.now(zona)
    corto = slug(nota['titulo']) + '-' + hashlib.md5(fuente.encode()).hexdigest()[:4]
    nombre = ahora.strftime('%Y-%m-%d') + '-' + corto + '.md'
    lineas = [
        '---',
        'layout: post',
        'title: ' + json.dumps(nota['titulo'], ensure_ascii=False),
        'date: ' + ahora.strftime('%Y-%m-%d %H:%M:%S') + ' -0300',
        '---',
        '',
        '**' + nota['bajada'].strip() + '**',
        '',
    ]
    for p in nota['cuerpo'].splitlines():
        if p.strip():
            lineas += [p.strip(), '']
    lineas.append('*Fuente: [' + urlparse(fuente).netloc + '](' + fuente + ')*')
    os.makedirs('_posts', exist_ok=True)
    with open('_posts/' + nombre, 'w', encoding='utf-8') as f:
        f.write(NL.join(lineas) + NL)
    return SITIO + ahora.strftime('/%Y/%m/%d/') + corto + '.html'


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


if __name__ == '__main__':
    estado = cargar()
    try:
        if sys.argv[1] == 'buscar':
            buscar(estado)
        elif sys.argv[1] == 'aprobar':
            aprobar(estado)
    finally:
        guardar(estado)
