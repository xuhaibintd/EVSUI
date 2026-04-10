from __future__ import annotations

import unittest
from pathlib import Path

from app.services.doc_modes.common import DOC_PIPELINE_UI_DEFAULTS
from app.services import multi_format


class MultiFormatWorkflowDefinitionTests(unittest.TestCase):
    def _create_values(self, **overrides: str) -> dict[str, str]:
        values = dict(DOC_PIPELINE_UI_DEFAULTS)
        values.update(overrides)
        return values

    def test_auto_route_uses_auto_partition_and_enrichment_chain(self) -> None:
        create_values = self._create_values(
            multi_format_strategy='auto',
            multi_format_enable_image_description='true',
            multi_format_enable_table_to_html='true',
            multi_format_enable_table_description='true',
            multi_format_enable_generative_ocr='true',
            multi_format_vlm_provider='openai',
            multi_format_vlm_model='gpt-4o',
        )
        request_parameters, warnings, processing_profile = multi_format._build_multi_format_workflow_definition(
            create_values=create_values,
            src=Path('sample.pdf'),
            partition_strategy='auto',
            languages=['eng'],
            chunk_size=600,
            chunk_overlap=80,
            include_orig_elements=False,
            overlap_all=True,
        )

        self.assertEqual(warnings, [])
        self.assertEqual(
            [node['name'] for node in request_parameters['workflow_nodes']],
            ['Partitioner', 'Image Description', 'Table to HTML', 'Table Description', 'Generative OCR', 'Chunker'],
        )
        partition_node = request_parameters['workflow_nodes'][0]
        self.assertEqual(partition_node['subtype'], 'vlm')
        self.assertEqual(partition_node['settings']['strategy'], 'auto')
        self.assertEqual(partition_node['settings']['provider'], 'openai')
        self.assertEqual(partition_node['settings']['model'], 'gpt-4o')
        self.assertTrue(processing_profile.startswith('partition:vlm:auto'))

    def test_hi_res_route_builds_partition_enrich_chunk_chain(self) -> None:
        create_values = self._create_values(
            multi_format_strategy='hi_res',
            multi_format_enable_image_description='true',
            multi_format_enable_table_to_html='true',
            multi_format_enable_table_description='true',
            multi_format_enable_generative_ocr='true',
        )
        request_parameters, warnings, processing_profile = multi_format._build_multi_format_workflow_definition(
            create_values=create_values,
            src=Path('sample.pdf'),
            partition_strategy='hi_res',
            languages=['eng'],
            chunk_size=600,
            chunk_overlap=80,
            include_orig_elements=False,
            overlap_all=True,
        )

        self.assertEqual(warnings, [])
        self.assertEqual(
            [node['name'] for node in request_parameters['workflow_nodes']],
            ['Partitioner', 'Image Description', 'Table to HTML', 'Table Description', 'Generative OCR', 'Chunker'],
        )
        self.assertTrue(processing_profile.endswith('chunk:chunk_by_character'))

    def test_fast_route_skips_enrichment_nodes(self) -> None:
        create_values = self._create_values(
            multi_format_strategy='fast',
            multi_format_enable_image_description='true',
            multi_format_enable_table_to_html='true',
            multi_format_enable_table_description='true',
            multi_format_enable_generative_ocr='true',
        )
        request_parameters, warnings, processing_profile = multi_format._build_multi_format_workflow_definition(
            create_values=create_values,
            src=Path('sample.pdf'),
            partition_strategy='fast',
            languages=['eng'],
            chunk_size=600,
            chunk_overlap=80,
            include_orig_elements=False,
            overlap_all=True,
        )

        self.assertEqual(warnings, [])
        self.assertEqual(
            [node['name'] for node in request_parameters['workflow_nodes']],
            ['Partitioner', 'Chunker'],
        )
        partition_node = request_parameters['workflow_nodes'][0]
        self.assertEqual(partition_node['subtype'], 'unstructured_api')
        self.assertEqual(partition_node['settings']['strategy'], 'fast')
        self.assertEqual(partition_node['settings']['ocr_languages'], ['eng'])
        self.assertEqual(processing_profile, 'partition:unstructured_api:fast,chunk:chunk_by_character')

    def test_vlm_route_skips_enrichment_nodes(self) -> None:
        create_values = self._create_values(
            multi_format_strategy='vlm',
            multi_format_enable_image_description='true',
            multi_format_enable_table_to_html='true',
            multi_format_enable_table_description='true',
            multi_format_enable_generative_ocr='true',
        )
        request_parameters, warnings, _processing_profile = multi_format._build_multi_format_workflow_definition(
            create_values=create_values,
            src=Path('sample.pdf'),
            partition_strategy='vlm',
            languages=[],
            chunk_size=600,
            chunk_overlap=80,
            include_orig_elements=False,
            overlap_all=True,
        )

        self.assertEqual(warnings, [])
        self.assertEqual(
            [node['name'] for node in request_parameters['workflow_nodes']],
            ['Partitioner', 'Chunker'],
        )

    def test_bookrag_reusable_workflow_builds_expected_node_order(self) -> None:
        create_values = self._create_values(
            multi_format_bookrag_workflow_name='BookRAG Raw Prod',
            multi_format_bookrag_enable_image_description='true',
            multi_format_bookrag_enable_table_to_html='true',
            multi_format_bookrag_enable_table_description='true',
            multi_format_bookrag_enable_generative_ocr='true',
            multi_format_bookrag_image_description_subtype='openai_image_description',
            multi_format_bookrag_table_to_html_subtype='openai_table2html',
            multi_format_bookrag_table_description_subtype='openai_table_description',
            multi_format_bookrag_generative_ocr_subtype='openai_ocr',
        )
        workflow_name, workflow_nodes, request_parameters, warnings, processing_profile = multi_format._build_bookrag_reusable_workflow_definition(
            create_values=create_values,
            partition_strategy='hi_res',
            languages=['eng'],
            image_partition_parameters={
                'infer_table_structure': True,
                'extract_image_block_types': ['Image', 'Table'],
                'unique_element_ids': True,
            },
        )

        self.assertEqual(warnings, [])
        self.assertEqual(workflow_name, 'BookRAG_Raw_Prod')
        self.assertEqual(request_parameters['workflow_name'], 'BookRAG_Raw_Prod')
        self.assertEqual(
            [node['name'] for node in workflow_nodes],
            ['Partitioner', 'Image Description', 'Table to HTML', 'Table Description', 'Generative OCR'],
        )
        self.assertEqual(workflow_nodes[0]['settings']['strategy'], 'hi_res')
        self.assertIn('image_description', processing_profile)
        self.assertIn('generative_ocr', processing_profile)

    def test_bookrag_auto_partition_warns_on_ignored_inputs(self) -> None:
        partition_node, request_parameters, warnings = multi_format._build_bookrag_workflow_partition_node(
            src=Path('sample.pdf'),
            partition_strategy='auto',
            languages=['eng'],
            image_partition_parameters={
                'extract_image_block_types': ['Image', 'Table'],
                'infer_table_structure': True,
                'unique_element_ids': True,
            },
        )

        self.assertEqual(partition_node['subtype'], 'vlm')
        self.assertEqual(partition_node['settings']['strategy'], 'auto')
        self.assertEqual(request_parameters['workflow_nodes'], [partition_node])
        self.assertEqual(len(warnings), 3)
        self.assertTrue(any('ocr_languages' in warning for warning in warnings))
        self.assertTrue(any('extract_image_block_types' in warning for warning in warnings))
        self.assertTrue(any('infer_table_structure' in warning for warning in warnings))


if __name__ == '__main__':
    unittest.main()
