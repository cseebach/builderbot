
from multiprocessing import Process
import time

from dropbox.client import DropboxClient
import bottle
from bottle import template, request

from builderbot.fingerprint import Fingerprint
from builderbot.build import do_build

app = bottle.Bottle()

DROPBOX_APP_KEY =    'zb2f9nrzan1qrhe'
DROPBOX_APP_SECRET = 'o9ex1s1gr7y4rb7'
ACCESS_TOKEN = 'rYp3ovb01OAAAAAAAAAD4otnwsa900C0uGhhvnvnN9PnydVFnOB6ae2Ze5ddeNlc'

@app.get("/dropbox-webhook")
def webhook_verify():
    return request.query.challenge

@app.post("/dropbox-webhook")
def webhook():
    user_ids = request.json["delta"]["users"]
    process = Process(target=build, args=(user_ids,))
    process.start()

### build methods

def check_and_build():
    client = DropboxClient(ACCESS_TOKEN)

    last = Fingerprint.get_last(client)
    latest = Fingerprint.get_latest(client)
    if last == latest:
        return

    latest.save(client)

    build_path = "builds/build_{}/".format(str(int(time.time())))

    do_build(build_path, client)

def build(user_ids):
    for user_id in user_ids:
        check_and_build()


app.run(host='0.0.0.0', port=18081, debug=True)
