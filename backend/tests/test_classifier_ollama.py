import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from api import app as api_app
from core import classifier


class OllamaChatTests(unittest.IsolatedAsyncioTestCase):
    async def test_gemma_uses_plain_json_prompt(self):
        requests = []

        def respond(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={"message": {"content": '{"ok": true}'}, "done_reason": "stop"})

        with patch.object(classifier, "PROVIDER", "ollama"), patch.object(classifier, "_ollama_structured", True):
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                result = await classifier._chat(client, "gemma4:e4b", "system", "user", {"type": "object"}, "detect")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(requests), 1)
        self.assertNotIn("format", requests[0])
        self.assertIn("Respond with ONLY one JSON object", requests[0]["messages"][0]["content"])

    async def test_other_ollama_models_keep_structured_output(self):
        requests = []
        schema = {"type": "object"}

        def respond(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={"message": {"content": '{"ok": true}'}, "done_reason": "stop"})

        with patch.object(classifier, "PROVIDER", "ollama"), patch.object(classifier, "_ollama_structured", True):
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                result = await classifier._chat(client, "other:model", "system", "user", schema, "verify")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(requests[0]["format"], schema)

    async def test_invalid_json_records_metadata_and_stays_fail_closed(self):
        content = '{"secret": "private",'
        response = httpx.Response(200, json={"message": {"content": content}, "done_reason": "length"})

        with self.assertRaises(classifier.ClassifierError) as caught:
            classifier._parse_ollama(response, structured=False, stage="verify")

        error = str(caught.exception)
        self.assertIn("stage=verify", error)
        self.assertIn("done_reason=length", error)
        self.assertIn(f"response_chars={len(content)}", error)
        self.assertNotIn("private", error)

        with patch.object(api_app.classifier, "classify", new=AsyncMock(side_effect=caught.exception)):
            result = await api_app.classify(api_app.TryIt(text="test", host="chatgpt.com"))
        self.assertEqual(result["tier"], "BLOCK")
        self.assertEqual(result["error"], error)

        with self.assertRaisesRegex(classifier.ClassifierError, "expected JSON object"):
            classifier._parse_ollama(
                httpx.Response(200, json={"message": {"content": "[]"}, "done_reason": "stop"}),
                structured=True,
                stage="detect",
            )


if __name__ == "__main__":
    unittest.main()
