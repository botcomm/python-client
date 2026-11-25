import unittest

from botcomm import Message


class PreviewMessages(unittest.TestCase):
    def test_optional_preview_decoding(self):
        self.assertIsNone(Message.from_json({"content": "Legacy"}).link_preview)
        message = Message.from_json({
            "linkPreview": {
                "url": "https://example.com",
                "siteName": "Example",
                "title": "Article",
                "image": {"id": "image", "width": 800, "height": 400},
            },
            "previewTS": "2026-10-09T10:00:00Z",
        })
        self.assertEqual(message.link_preview.site_name, "Example")
        self.assertEqual(message.link_preview.image.width, 800)
        self.assertIsNotNone(message.preview_ts)
