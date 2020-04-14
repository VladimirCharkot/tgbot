# coding=utf-8

import schedule
import logging
import re
import json
import telegram
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


# Datos hardcodeados con toda justicia:
with open('conf.json') as f:
    conf = json.loads(f.read())

onboard_key = conf['onboard_key']
bot_token = conf['bot_token']
admins = conf['admins']


### Archivos ###

# Hay tres índices que hay que mantener. Para garantizar sincronía,
# cada vez que hacemos un update a alguno, también lo planchamos a disco.
# Eso quedaría más bonito con una DB, pero no hace rollo.

# Carga json de un archivo. Si no existe, lo crea vacío
# fname -> dict
def loadOrCreate(fname):
    data = {}
    try:
        with open(fname, 'r') as f:
            c = f.read()
            data = json.loads(c)
    except FileNotFoundError:
        logging.info("Archivo {} no encontrado... creando".format(fname))
        with open(fname, 'w') as f:
            f.write(json.dumps({}))
    return data

# Enlaces: mapeo de círculo a responsable
# {'magia' : {'nombre' : 'vlad', 'username' : 'vlado', 'chat_id' : 374297927923}, ...}

# Pendientes: telegram no admite que un bot _inicie_ un chat. Por lo tanto, si un admin agrega
# un enlace, éste tiene que de alguna manera iniciar un chat con este bot antes de que pueda
# contactársele. Éste mapeo guarda a esxs "admins pendientes de confirmación"
# Por eso hay dos comandos: onboard (de admin) y onboardme (de enlace)
# {'raulio' : ['formación','comunicación',...], ...}

# Usuaries: chat_ids de les usuaries que hayan escrito alguna vez usando el comando /talkto
# {'equiserrito' : 74287420442, ...}

enlaces = loadOrCreate('enlaces.json')  # indexado por círculo
pendientes = loadOrCreate('pendientes.json')  # indexado por user
usuaries = loadOrCreate('usuaries.json')  # indexado por user

### Definición de las funciones que mantienen la ram planchada a disco
def flush_enlaces():
    with open('enlaces.json', 'w') as f:
        f.write(json.dumps(enlaces))


def flush_pendientes():
    with open('pendientes.json', 'w') as f:
        f.write(json.dumps(pendientes))


def flush_usuaries():
    with open('usuaries.json', 'w') as f:
        f.write(json.dumps(usuaries))


### Funciones del bot ###

# Patrones de comandos
talkto_pattern = re.compile('/talkto @?(?P<circ>\w+) (?P<msg>.+)$')
resp_pattern = re.compile('/resp @?(?P<user>\w+) (?P<msg>.+)$')
onboard_pattern = re.compile('/onboard @?(?P<user>\w+) (?P<circ>\w+) (?P<key>\w+)$')
deboard_pattern = re.compile('/deboard @?(?P<user>\w+) (?P<key>\w+)$')


# Start
hola_text = r"""Bienvenide
Soy proxybot\. 
Hay una lista de círculos con los que te puede interesar contactar\.
Como sus responsables van rotando, yo me ocupo de hacer el puente\.
Usá el comando `/talkto [círculo] [mensaje]` para enviar _mensaje_ a _círculo_ y el comando `/index` para ver los círculos disponibles\.
Abrazobot\."""


def start(update, context):
    context.bot.send_message(chat_id=update.effective_chat.id,
                             text=hola_text,
                             parse_mode=telegram.ParseMode.MARKDOWN_V2)


# Ping
def ping(update, context):
    pong = "Pong, amigue"
    username = update['message']['chat']['username'].lower()
    circulos_user = [c for c in enlaces if enlaces[c]['username'] == username]
    if username in admins:
        pong += "\n¡Vous êtes admin! Such wow"
    if circulos_user:
        pong += "\nEstás delegade como forward de {}".format(', '.join(circulos_user))
    if username in pendientes:
        pong += "\nEstás pendiente para {}. Mandame `/onboardme` para confirmar el alta.".format(', '.join(pendientes[username]))
    context.bot.send_message(chat_id=update.effective_chat.id, text=pong)

# Círculos disponibles
def index(update, context):
    context.bot.send_message(chat_id=update.effective_chat.id,
                             text="Los círculos disponibles son:\n`{}`\nContactá con cualquiera de ellos con el comando\n/talkto _círculo_ _mensaje_".format(
                                 '\n'.join(enlaces.keys())),
                             parse_mode=telegram.ParseMode.MARKDOWN_V2)

# Proxy: talktoear con un círculo
def talkto(update, context):
    # Chequeo si el comando matchea la estructura. Sino, return.
    m = talkto_pattern.match(update['message']['text'])
    if not m:
        context.bot.send_message(chat_id=update.effective_chat.id,
                                 text="No entiendo\. La sintaxis es:\n`/talkto _círculo_ _mensaje..._`\nUsá /index para consultar los círculos disponibles\.",
                                 parse_mode=telegram.ParseMode.MARKDOWN_V2)
        return

    # Chequeo si el círculo que me están pidiendo está indexado. Sino, return.
    circ = m.group('circ')  # círculo matcheado en el comando
    msg = m.group('msg')    # mensaje matcheado en el comando
    if not circ in enlaces:
        context.bot.send_message(chat_id=update.effective_chat.id,
                                 text="Nope, no tengo ese círculo indexado...".format(circ))
        context.bot.send_message(chat_id=update.effective_chat.id,
                                 text="Los círculos disponibles son:\n{}\nContactá con cualquiera de ellos con el comando /talkto _círculo_ _mensaje\.\.\._".format(
                                     '\n'.join(enlaces.keys())),
                                 parse_mode=telegram.ParseMode.MARKDOWN_V2)
        return

    # Info que viene del mensaje, en el objeto update
    user_info = {'nombre': update['message']['chat']['first_name'],
                 'username': update['message']['chat']['username'].lower(),
                 'chat_id': update['message']['chat']['id']}

    # Checkeo si tengo al user indexado y si no lo indexo.
    # Es necesario para responderle más adelante, con el chat_id
    if user_info['username'] not in usuaries:
        usuaries[user_info['username']] = {'nombre': user_info['nombre'], 'chat_id': user_info['chat_id']}
        flush_usuaries()

    # Mando mensaje al enlace
    context.bot.send_message(chat_id=enlaces[circ]['chat_id'],
                             text="Hola {},\n{} \(@{}\) dice via {}:\n\n{}\n\nRespodele con /resp @{} msg".format(
                                 enlaces[circ]['nombre'], user_info['nombre'], user_info['username'], circ, msg,
                                 user_info['username']),
                             parse_mode=telegram.ParseMode.MARKDOWN_V2)
    # Recibido a le pibe
    context.bot.send_message(chat_id=update.effective_chat.id, text="Tu mensaje fue enviado al usuarie enlace de {}...".format(circ))


# Proxy: responder a un usuario que contactó vía talkto
def resp(update, context):
    # Comando que usan les users enlace para responder a los talkto. La alternativa es un mensaje directo
    m = resp_pattern.match(update['message']['text'])
    if not m:
        context.bot.send_message(chat_id=update.effective_chat.id,
                                 text="No entiendo\. La sintaxis es:\n`/resp _user_ _mensaje\.\.\._`",
                                 parse_mode=telegram.ParseMode.MARKDOWN_V2)
        return

    if not update['message']['chat']['username'].lower() in [enlaces[c]['username'] for c in enlaces]:
        context.bot.send_message(chat_id=update.effective_chat.id,
                                 text="Sólo usuaries enlace pueden usar este comando")
        return

    target_user = m.group('user')
    msg = m.group('msg')
    if not target_user in usuaries:
        context.bot.send_message(chat_id=update.effective_chat.id,
                                 text="Nope, no tengo ese user indexado... "
                                      "tiene que hablarle al bot antes que el bot pueda hablarle")

    context.bot.send_message(chat_id=usuaries[target_user]['chat_id'],
                             text="Hola {},\nel enlace ({}) dice:\n\n{}".format(usuaries[target_user]['nombre'], update['message']['chat']['first_name'], msg))

# Para ejecutar cuando llega texto sin comando
def echo(update, context):
    context.bot.send_message(chat_id=update.effective_chat.id, text="Disculpe, no hablo humano...")
    index(update, context)


def deboard(update, context):
    m = deboard_pattern.match(update['message']['text'])
    if not m:
        context.bot.send_message(chat_id=update.effective_chat.id,
                                 text="No entiendo\. La sintaxis es `/deboard [user] [clave]`\. Mirá que es un comando para admins\.",
                                 parse_mode=telegram.ParseMode.MARKDOWN_V2)
        return

    logging.info("Recibiendo /deboard {}".format(m.group('user')))
    username = update['message']['chat']['username'].lower()
    if not username in admins:
        context.bot.send_message(chat_id=update.effective_chat.id, text="No estás cargade como admin")
        return
    if not m.group('key') == onboard_key:
        context.bot.send_message(chat_id=update.effective_chat.id, text="Hmmm... esa no es la clave")
        return

    db_user = m.group('user')
    circs_de_este_user = [c for c in enlaces if enlaces[c]['username'] == db_user]
    for c in circs_de_este_user:
        enlaces.pop(c)

    if db_user in pendientes:
        pendientes.pop(db_user)

    if not circs_de_este_user and not db_user in pendientes:
        texto = "Ese user no aparece por ningún lado... ¿Está bien escrito? Recordá que va username, no nombre"
        context.bot.send_message(chat_id=update.effective_chat.id, text=texto)
        return

    texto = "Listo. "
    if circs_de_este_user:
        texto += "{} {} sin user".format(', '.join(circs_de_este_user), "quedó" if len(circs_de_este_user)==1 else "quedaron")

    flush_enlaces()
    flush_pendientes()
    context.bot.send_message(chat_id=update.effective_chat.id, text=texto)


def onboard(update, context):
    m = onboard_pattern.match(update['message']['text'])
    if not m:
        context.bot.send_message(chat_id=update.effective_chat.id,
                                 text="No entiendo\. La sintaxis es `/onboard _user círculo clave_`\. Mirá que es un comando para admins\.",
                                 parse_mode=telegram.ParseMode.MARKDOWN_V2)
        return

    logging.info("Recibiendo /onboard {} {} {}".format(m.group('user'), m.group('circ'), m.group('key')))
    username = update['message']['chat']['username'].lower()
    if not username in admins:
        context.bot.send_message(chat_id=update.effective_chat.id, text="No estás cargade como admin")
        return

    if not m.group('key') == onboard_key:
        context.bot.send_message(chat_id=update.effective_chat.id, text="Hmmm... esa no es la clave")
        return

    ob_user = m.group('user')
    if ob_user in pendientes:
        pendientes[ob_user].append(m.group('circ'))
    else:
        pendientes.update({m.group('user'): [m.group('circ')]})

    flush_pendientes()

    logging.info("{} cargade y a la espera de confirmación!".format(username))
    context.bot.send_message(chat_id=update.effective_chat.id,
                             text="¡Enlace creado! Ahora {} está seteade como forward de {}... esperamos su confirmación. Avisale que me hable y ejecute /onboardme".format(
                                 m.group('user'), m.group('circ')))


def onboardme(update, context):
    username = update['message']['chat']['username'].lower()
    if not username in pendientes:
        context.bot.send_message(chat_id=update.effective_chat.id,
                                 text="No estás listade para dar de alta\. Si debieras, porfa contactá a un admin\."
                                      "Podés usar el comando `/at_admin [mensaje]`\. "
                                      "Antes quizás quieras verificar tu status con `/ping`\.",
                                 parse_mode=telegram.ParseMode.MARKDOWN_V2)
        return

    circs = pendientes[username]
    for circ in circs:
        enlaces.update({circ: {'chat_id': update['message']['chat']['id'],
                               'nombre': update['message']['chat']['first_name'],
                               'username': username
                               }})
    pendientes.pop(username)
    flush_enlaces()
    flush_pendientes()
    logging.info("{} (@{}) acaba de darse de alta como forward de {}".format(update['message']['chat']['first_name'], username, ', '.join(circs)))
    context.bot.send_message(chat_id=update.effective_chat.id,
                             text="¡Listo! Te diste de alta como forward de {}".format(', '.join(circs)))
    for adm, adm_chat_id in admins.items():
        for circ in circs:
            context.bot.send_message(chat_id=adm_chat_id, text="{} (@{}) acaba de darse de alta como forward de {}".format(
                update['message']['chat']['first_name'], username, circ))

# Dump de consola
def dump(update, context):
    logging.info("#---------------#")
    logging.info("¡Dump!".center(17))
    logging.info("#---------------#")
    logging.info("Enlaces registrados:")
    logging.info('\n'.join(["{} - {} (@{})".format(c, enlaces[c]['nombre'], enlaces[c]['username']) for c in
                            enlaces]) if enlaces else "Ups... ¡no hay enlaces!")
    logging.info("-----".center(17))
    logging.info("Enlaces pendientes:")
    logging.info('\n'.join(
        ["@{} -> {}".format(u, pendientes[u]) for u in pendientes]) if pendientes else "¡No hay pendientes!")
    logging.info("-----".center(17))
    logging.info("Usuaries registrades:")
    logging.info(', '.join(usuaries.keys()) if usuaries else "¡No hay usuaries!")
    logging.info('{} usuaries en total'.format(len(usuaries)))
    logging.info("#---------------#")


# Updater, dispatcher y handlers
b_upd = Updater(token=bot_token, use_context=True)
b_dsp = b_upd.dispatcher

start_handler = CommandHandler('start', start)
b_dsp.add_handler(start_handler)

ping_handler = CommandHandler('ping', ping)
b_dsp.add_handler(ping_handler)

index_handler = CommandHandler('index', index)
b_dsp.add_handler(index_handler)

talkto_handler = CommandHandler('talkto', talkto)
b_dsp.add_handler(talkto_handler)

resp_handler = CommandHandler('resp', resp)
b_dsp.add_handler(resp_handler)

onboard_handler = CommandHandler('onboard', onboard)
b_dsp.add_handler(onboard_handler)

deboard_handler = CommandHandler('deboard', deboard)
b_dsp.add_handler(deboard_handler)

onboardme_handler = CommandHandler('onboardme', onboardme)
b_dsp.add_handler(onboardme_handler)

dump_handler = CommandHandler('dump', dump)
b_dsp.add_handler(dump_handler)

echo_handler = MessageHandler(Filters.text, echo)
b_dsp.add_handler(echo_handler)


# Loop
if __name__ == '__main__':
    print("Escuchando...")
    try:
        b_upd.start_polling()
    except KeyboardInterrupt:
        print("\nBye :)")
    except Exception as e:
        print(str(e))
    # Antes de morirte salvame los datos no matter what:
    finally:
        flush_enlaces()
        flush_pendientes()
        flush_usuaries()

    # (igual todo este try me parece que no está funcionando porque
    #  corriendo en algún thread o algo así...)

"""
{
    "update_id": 511906544,
    "message": {
        "message_id": 23,
        "date": 1586821897,
        "chat": {
            "id": 903631368,
            "type": "private",
            "username": "Vladogno",
            "first_name": "Vlad"
        },
        "text": "/start",
        "entities": [
            {
            "type": "bot_command",
            "offset": 0,
            "length": 6
            }
        ],
        "caption_entities": [],
        "photo": [],
        "new_chat_members": [],
        "new_chat_photo": [],
        "delete_chat_photo": false,
        "group_chat_created": false,
        "supergroup_chat_created": false,
        "channel_chat_created": false,
        "from": {
            "id": 903631368,
            "first_name": "Vlad",
            "is_bot": false,
            "username": "Vladogno",
            "language_code": "en"
        }
    },
    "_effective_user": {
    "id": 903631368,
    "first_name": "Vlad",
    "is_bot": false,
    "username": "Vladogno",
    "language_code": "en"
    },
    "_effective_chat": {
    "id": 903631368,
    "type": "private",
    "username": "Vladogno",
    "first_name": "Vlad"
    },
    "_effective_message": {
    "message_id": 23,
    "date": 1586821897,
    "chat": {
    "id": 903631368,
    "type": "private",
    "username": "Vladogno",
    "first_name": "Vlad"
    },
    "text": "/start",
    "entities": [
    {
    "type": "bot_command",
    "offset": 0,
    "length": 6
    }
    ],
    "caption_entities": [],
    "photo": [],
    "new_chat_members": [],
    "new_chat_photo": [],
    "delete_chat_photo": false,
    "group_chat_created": false,
    "supergroup_chat_created": false,
    "channel_chat_created": false,
    "from": {
    "id": 903631368,
    "first_name": "Vlad",
    "is_bot": false,
    "username": "Vladogno",
    "language_code": "en"
    }
    }
}
"""
