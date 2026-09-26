import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from on_call_assistant.integrations.model import AnthropicModel, LangChainModel, create_model


class FakeChatModel:
    def __init__(self, content='{"capability":"bug_analysis"}', stop_reason="end_turn"):
        self.content = content
        self.stop_reason = stop_reason
        self.messages = None

    def invoke(self, messages):
        self.messages = messages
        return SimpleNamespace(
            text=self.content,
            response_metadata={"stop_reason": self.stop_reason},
            usage_metadata={"total_tokens": 17},
        )


class ModelTests(unittest.TestCase):
    def test_anthropic_messages_adapter_returns_json_and_usage(self):
        client = FakeChatModel()
        model = AnthropicModel(client=client)
        result, tokens = model.complete_json("Classify", {"request": {"text": "Investigate"}})
        self.assertEqual(result, {"capability": "bug_analysis"})
        self.assertEqual(tokens, 17)
        self.assertEqual(model.model, "claude-sonnet-5")
        self.assertEqual(json.loads(client.messages[1][1]),
                         {"request": {"text": "Investigate"}})

    def test_anthropic_rejects_truncated_or_non_object_response(self):
        for client, error in ((FakeChatModel(stop_reason="max_tokens"), "truncated"),
                              (FakeChatModel(content="[]"), "JSON object")):
            with self.subTest(error=error):
                model = AnthropicModel(client=client)
                with self.assertRaisesRegex(ValueError, error):
                    model.complete_json("Classify", {})

    def test_placeholder_key_is_rejected_without_api_call(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "replace-with-your-anthropic-key"}):
            with self.assertRaisesRegex(ValueError, "Set ANTHROPIC_API_KEY"):
                AnthropicModel()

    def test_factory_selects_provider(self):
        with patch.dict(os.environ, {"OCA_MODEL_PROVIDER": "anthropic",
                                  "ANTHROPIC_API_KEY": "replace-with-your-anthropic-key"}):
            with self.assertRaisesRegex(ValueError, "Set ANTHROPIC_API_KEY"):
                create_model()
        with patch.dict(os.environ, {"OCA_MODEL_PROVIDER": "unsupported"}):
            with self.assertRaisesRegex(ValueError, "Unsupported provider"):
                create_model()
        with patch.dict(os.environ, {"OCA_MODEL_PROVIDER": "anthropic", "OCA_MODEL": "claude-sonnet-5"}):
            self.assertEqual(LangChainModel(client=FakeChatModel()).provider, "anthropic")

    def test_factory_can_instantiate_both_installed_providers_without_network(self):
        cases = (
            ({"OCA_MODEL_PROVIDER": "anthropic", "OCA_MODEL": "claude-sonnet-5",
              "ANTHROPIC_API_KEY": "test-only-key"}, "ChatAnthropic"),
            ({"OCA_MODEL_PROVIDER": "openai", "OCA_MODEL": "gpt-4.1-mini",
              "OPENAI_API_KEY": "test-only-key"}, "ChatOpenAI"),
        )
        for env, expected_client in cases:
            with self.subTest(provider=env["OCA_MODEL_PROVIDER"]), patch.dict(os.environ, env):
                model = create_model()
                if env["OCA_MODEL_PROVIDER"] == "openai":
                    self.assertEqual(type(model.client.bound).__name__, expected_client)
                    self.assertEqual(model.client.kwargs["response_format"], {"type": "json_object"})
                else:
                    self.assertEqual(type(model.client).__name__, expected_client)


if __name__ == "__main__":
    unittest.main()
