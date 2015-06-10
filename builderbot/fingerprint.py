import json

from dropbox.rest import ErrorResponse

class Fingerprint(object):

    def __init__(self, data):
        self.data = data

    def __eq__(self, other):
        return self.data == other.data

    def __ne__(self, other):
        return not self.__eq__(other)

    def save(self, dropbox):
        dropbox.put_file("/builds/last_build.json", json.dumps(self.data), overwrite=True)

    @staticmethod
    def get_latest(dropbox):
        art_rev = dropbox.metadata("/art", list=False)["rev"]
        cards_rev = dropbox.metadata("/cards", list=False)["rev"]
        graphics_rev = dropbox.metadata("/graphics", list=False)["rev"]

        data = {"art":art_rev, "cards":cards_rev, "graphics": graphics_rev}
        return Fingerprint(data)

    @staticmethod
    def get_last(dropbox):
        try:
            last_build_json = dropbox.get_file("/builds/last_build.json").read()
            last_build = json.loads(last_build_json.decode("utf-8"))
        except ErrorResponse:
            last_build = {}
        return Fingerprint(last_build)
