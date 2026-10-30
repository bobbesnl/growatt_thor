"""Translation shape and format placeholders must match the English contract."""

import json
import re
import sys
import unittest

from tests.support import PACKAGE_PATH

LANGUAGES = ("en", "de", "nl", "fr", "es", "it", "hu", "sl")
PLACEHOLDERS = re.compile(r"\{([a-zA-Z_][a-zA-Z_0-9]*)\}")


def flatten(value, prefix=""):
    return {
        path: text
        for key, item in value.items()
        for path, text in (
            flatten(item, prefix + key + ".").items()
            if isinstance(item, dict)
            else [(prefix + key, item)]
        )
    }


def translations():
    return {
        language: flatten(
            json.loads((PACKAGE_PATH / "translations" / (language + ".json")).read_text())
        )
        for language in LANGUAGES
    }


def identical_to_english():
    locales = translations()
    english = locales["en"]
    return {
        language: {key: value for key, value in english.items() if locale.get(key) == value}
        for language, locale in locales.items()
        if language != "en"
    }


class TranslationParityTest(unittest.TestCase):
    def test_all_languages_have_identical_keys(self):
        locales = translations()
        for language, locale in locales.items():
            with self.subTest(language=language):
                self.assertEqual(locale.keys(), locales["en"].keys())

    def test_localized_descriptions_do_not_retain_english_sentences(self):
        locales = translations()
        for language, locale in locales.items():
            if language == "en":
                continue
            for key, english in locales["en"].items():
                for sentence in re.split(r"(?<=[.!?])\s+", english):
                    # Short labels and protocol names may legitimately be shared.
                    if len(sentence) >= 45:
                        with self.subTest(language=language, key=key, sentence=sentence):
                            self.assertNotIn(sentence, locale[key])

    def test_format_placeholders_are_preserved(self):
        locales = translations()
        for language, locale in locales.items():
            for key, text in locale.items():
                with self.subTest(language=language, key=key):
                    self.assertEqual(
                        set(PLACEHOLDERS.findall(text)),
                        set(PLACEHOLDERS.findall(locales["en"][key])),
                    )


if __name__ == "__main__":
    if "--report" in sys.argv:
        print(json.dumps(identical_to_english(), indent=2, ensure_ascii=False))
    else:
        unittest.main()
