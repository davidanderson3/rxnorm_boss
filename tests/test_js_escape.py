import json
import unittest

from boss import _js_escape


class JsEscapeTests(unittest.TestCase):
    def test_escape_html_comment_sequences(self):
        data = "<!-- tricky -->"
        dumped = json.dumps(data, ensure_ascii=False)
        escaped = _js_escape(dumped)
        self.assertNotIn("<!--", escaped)
        self.assertNotIn("-->", escaped)
        self.assertIn("<\\!--", escaped)
        self.assertIn("--\\>", escaped)

    def test_escape_script_close(self):
        data = "</script>"
        dumped = json.dumps(data, ensure_ascii=False)
        escaped = _js_escape(dumped)
        self.assertNotIn("</", escaped)
        self.assertIn("<\\/", escaped)


if __name__ == "__main__":
    unittest.main()
