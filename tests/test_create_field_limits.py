import unittest

from app.core.form_fields import CreateFieldValidationError, validate_create_field
from app.services.create_config import CREATE_FIELD_MAX_LEN
from app.services.doc_modes.constants import collect_doc_pipeline_ui_values


class CreateFieldLimitTests(unittest.TestCase):
    def test_credentials_paths_and_prompts_preserve_full_values(self):
        secret = "fixture-" + "a" * 256
        values = collect_doc_pipeline_ui_values({"multi_format_vlm_provider_api_key": secret},
                                                field_max_len=CREATE_FIELD_MAX_LEN)
        self.assertEqual(values["multi_format_vlm_provider_api_key"], secret)
        for name, value in (("document_files", "uploads/" + "document/" * 300), ("prompt", "Question " * 1000)):
            self.assertEqual(validate_create_field(name, value), value)

    def test_oversized_keys_and_identifiers_raise_without_echoing_value(self):
        for name, value in (("multi_format_vlm_provider_api_key", "secret-marker" * 1000),
                            ("vector_store_name", "n" * 129)):
            with self.subTest(name=name), self.assertRaises(CreateFieldValidationError) as raised:
                validate_create_field(name, value)
            self.assertNotIn(value, str(raised.exception))
