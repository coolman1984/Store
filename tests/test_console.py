"""The Windows console may not speak Arabic and a double-clicked program may have no console: neither may stop the server
(found by the Windows smoke test of the first installer build)."""
import io
import sys
import unittest

from harness import ROOT
import app

assert ROOT  # importing harness puts server/ on the path


class Ascii(io.TextIOBase):
    def write(self, text):
        text.encode('cp1252')  # raises UnicodeEncodeError for Arabic, like a Windows code-page console
        return len(text)


class ConsoleTests(unittest.TestCase):
    def test_arabic_text_on_a_console_that_cannot_show_it(self):
        real, sys.stdout = sys.stdout, Ascii()
        try:
            app.say('الستور يعمل الآن')
        finally:
            sys.stdout = real

    def test_no_console_at_all(self):
        real, sys.stdout = sys.stdout, None
        try:
            app.say('الستور')
        finally:
            sys.stdout = real


if __name__ == '__main__':
    unittest.main()
