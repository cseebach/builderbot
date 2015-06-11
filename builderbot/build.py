import configparser
import argparse
import time
from pathlib import Path
import shutil
import os
import hashlib
import json
from collections import namedtuple, defaultdict

from PIL import Image, ImageDraw, ImageFont
import yaml
from dropbox.rest import ErrorResponse
from PyPDF2 import PdfFileReader, PdfFileMerger

title_size = 56
rules_size = 40
flavor_size = 30
title_placement = (89, 79)
rules_placement = (89, 590)
flavor_placement = (89, 950)

import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(filename="build.log.txt")
handler.setLevel(logging.DEBUG)
logger.addHandler(handler)


class CardImage(object):

    def __init__(self, art, graphics):
        self.art = art
        self.graphics = graphics

    def set_background(self, name):
        image = Image.open(str(self.art.get(name)))
        self.image = image.convert("RGBA")
        image.close()

    def add_panels(self):
        panels = Image.open(str(self.graphics.get("text_boxes.png")))
        image = self.image
        self.image = Image.alpha_composite(self.image, panels)
        panels.close()
        image.close()

    def draw_bounded_text(self, drawer, text, placement, into, font):
        left_bound = placement[0]
        right_bound = into.size[0] - placement[0]
        max_width = right_bound - left_bound

        current_y = placement[1]
        line_height = font.getsize("A")[1] + 10
        x = placement[0]
        for line in text.split(u"\n"):
            to_draw = line.split()
            if not to_draw:
                to_draw = [" "]
            extra = []
            while to_draw or extra:
                while font.getsize(u" ".join(to_draw))[0] > max_width:
                    extra = [to_draw[-1]] + extra
                    to_draw = to_draw[:-1]
                drawer.text((x, current_y), u" ".join(to_draw), (0,0,0), font=font)
                current_y += line_height
                to_draw = extra
                extra = []

    def add_rules(self, rules):
        font_path = str(self.graphics.get("font.ttf"))
        font = ImageFont.truetype(font_path, rules_size)

        drawer = ImageDraw.Draw(self.image)
        self.draw_bounded_text(drawer, rules, rules_placement, self.image, font)

    def add_title(self, title):
        font_path = str(self.graphics.get("font.ttf"))
        font = ImageFont.truetype(font_path, title_size)

        drawer = ImageDraw.Draw(self.image)
        drawer.text(title_placement, title, (0,0,0), font=font)

    def save(self, path):
        image = self.image.convert("RGB")
        image.save(str(path), quality=90)
        image.close()

    def close(self):
        self.image.close()


remove_chars = "`~!@#$%^&*()-=+{}[]|\;:'<>,./?" + '"'
def slugify(name):
    unspaced = name.lower().replace(" ", "_")
    for char in remove_chars:
        unspaced = unspaced.replace(char, "")
    return unspaced

class Card(object):

    def __init__(self, card_data, index):
        self.data = card_data
        self.name = card_data["name"]
        self.index = index
        self.art_name, self.product_name = self.get_paths()

    def get_paths(self):
        slugified = slugify(self.name)
        art_name = slugified+".png"
        product_name = "{:03}_{}".format(self.index, slugified)

        return art_name, product_name

    def get_rules_text(self):
        card = self.data

        types = card["types"]+u"\n"
        cost = u"Cost: {}\n".format(card["cost"]) if "cost" in card else ""
        combat = u"Combat: {}\n".format(card["combat"]) if "combat" in card else ""
        rules = card["rules"]
        return types + cost + combat + "\n" + rules

class CacheEntry(object):

    def __init__(self):
        self.in_dropbox = None
        self.in_cache = None

class CacheCollection(object):

    def __init__(self, cache_dir, name, dropbox):
        self.entries = defaultdict(CacheEntry)
        self.cache_dir = cache_dir
        self.name = name
        self.dropbox = dropbox

        self.load_current(name)
        self.load_cached(name)

    def load_current(self, entries):
        entries = self.dropbox.metadata("/"+self.name+"/", list=True)["contents"]
        for entry in entries:
            path = entry["path"]
            revision = entry["rev"]
            self.entries[path].in_dropbox = revision

    def load_cached(self, name):
        cache_path = Path(self.cache_dir, self.name+".cached.yml")
        if not cache_path.exists():
            return

        with cache_path.open() as cache_yaml:
            cached = yaml.load(cache_yaml)

        for path, revision in cached.items():
            self.entries[path].in_cache = revision

    def get(self, name):
        if not name.startswith("/"+self.name+"/"):
            name = "/"+self.name+"/"+name

        entry = self.entries[name]

        if not entry.in_dropbox:
            return None
        elif entry.in_dropbox != entry.in_cache:
            self.download_entry(name)

        return Path(self.cache_dir, name.lstrip("/")) if entry.in_cache else None

    def download_entry(self, name):
        destination_path = Path(self.cache_dir, name.lstrip("/"))
        logger.info("Caching a file to "+str(destination_path))
        try:
            logger.info("opening dropbox file "+name)
            with self.dropbox.get_file(name) as pointer:
                logger.info("opened successfully")
                if not destination_path.parent.exists():
                    destination_path.parent.mkdir(parents=True)
                with destination_path.open("wb") as destination:
                    destination.write(pointer.read())
            logger.info("downloaded file "+str(destination_path))

            entry = self.entries[name]
            entry.in_cache = entry.in_dropbox

            return destination_path
        except ErrorResponse:
            logger.info("Couldn't get the file.")
            return

    def save(self):
        cache_path = Path(self.cache_dir, self.name+".cached.yml")

        just_cache = {}
        for path, status in self.entries.items():
            if status.in_cache:
                just_cache[path] = status.in_cache

        with cache_path.open("w") as cache_yaml:
            yaml.dump(self.entries, just_cache)

    def filter(self, suffix):
        for path in self.entries.keys():
            if path.endswith(suffix):
                yield path

    # takes a directory, a name, and a list of file entries from dropbox
    # remembers:
        # if a file currently exists
        # what revision is cached in the directory
    # stores all this in
        # a yaml file named after the given name
    # has operations:
        # get
            # if a file does not exist
                # return None
            # else
                # if we have the old version, download the new one
                # return the full path of the item in the cache

class Cache(object):

    def __init__(self, dropbox):
        logger.info("Building a cache")
        self.dropbox = dropbox
        self.directory = Path("cache")
        if not self.directory.exists():
            self.directory.mkdir(parents=True)
        self.load()

    def load(self):
        logger.info("cache for: art")
        self.art = CacheCollection(self.directory, "art", self.dropbox)
        logger.info("cache for: cards")
        self.cards = CacheCollection(self.directory, "cards", self.dropbox)
        logger.info("cache for: graphics")
        self.graphics = CacheCollection(self.directory, "graphics", self.dropbox)

    def save(self):
        self.art.save()
        self.cards.save()
        self.graphics.save()


class BuilderBot(object):

    def __init__(self, path, dropbox):
        self.dropbox = dropbox
        self.path = path

    def yield_cards(self, cache):
        logger.info("Looking for card files.")
        for cards_path in sorted(cache.cards.filter(".yml")):
            logger.info("One found at "+str(cards_path))
            cards_path = cache.cards.get(cards_path)
            with cards_path.open() as cards_yaml:
                for card in yaml.load_all(cards_yaml):
                    yield card

    def make_image(self, card, cache):
        card_image = CardImage(cache.art, cache.graphics)
        card_image.set_background(card.art_name)
        card_image.add_panels()
        card_image.add_rules(card.get_rules_text())
        card_image.add_title(card.name)
        return card_image

    def save_to_dropbox_and_server(self, card_image, dropbox_path):
        on_server = Path(dropbox_path.lstrip("/"))
        if not on_server.parent.exists():
            on_server.parent.mkdir(parents=True)
        card_image.save(on_server)
        with on_server.open("rb") as image_file:
            self.dropbox.put_file(dropbox_path, image_file)

    def save_jpeg(self, card, card_image):
        on_dropbox = "{}/singles/{}.jpg".format(self.path, card.product_name)
        self.save_to_dropbox_and_server(card_image, on_dropbox)

    def save_pdf(self, card, card_image):
        on_dropbox = "{}/singles/{}.pdf".format(self.path, card.product_name)
        self.save_to_dropbox_and_server(card_image, on_dropbox)

    def save_duplicate_pdf(self, card, card_image):
        on_dropbox = "{}/duplicates/{}".format(self.path, card.product_name)
        on_server = Path(on_dropbox.lstrip("/"))
        if not on_server.parent.exists():
            on_server.parent.mkdir(parents=True)

        single = "{}/singles/{}.pdf".format(
            self.path.lstrip("/"), card.product_name)

        merger = PdfFileMerger()
        for i in range(card.data["quantity"]):
            merger.append(single)
        merger.write(str(on_server))
        merger.close()

        with on_server.open("rb") as image_file:
            self.dropbox.put_file(on_dropbox, image_file)


    def build(self):
        logger.info("---")
        logger.info("Starting a build on path: "+self.path)
        Path(self.path, "singles").mkdir(parents=True)

        cache = Cache(self.dropbox)
        for index, card_data in enumerate(self.yield_cards(cache)):
            card = Card(card_data, index+1)

            card_image = self.make_image(card, cache)

            self.save_jpeg(card, card_image)
            self.save_pdf(card, card_image)
            self.save_duplicate_pdf(card, card_image)

            card_image.close()


def do_build(path, dropbox):
    bot = BuilderBot(path, dropbox)
    bot.build()
