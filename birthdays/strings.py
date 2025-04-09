from json import load
from os import path

log = getLogger("red.blu.strings")

class Strings:
    def __init__(self, lang='en', default_lang='en'):
        self.strings = {}
        self.lang = lang
        self.default_lang = default_lang
        self.load_strings(default_lang)

    def load_strings(self, lang):
        strings_file_path = f"strings/{lang}.json"
        log.error(path.abspath(strings_file_path))
        if path.exists(strings_file_path):
            with open(strings_file_path, 'r', encoding='utf-8') as file:
                self.strings[lang] = load(file)
        else:
            log.error(f"{strings_file_path} does not exist!")
            self.strings[lang] = {}

    def get(self, id, lang=None):
        lang = lang or self.lang or self.default_lang
        if lang not in self.strings:
            self.load_strings(lang)
        return self.strings.get(lang, {}).get(id, self.strings[self.default_lang].get(id, id))