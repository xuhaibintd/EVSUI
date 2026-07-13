from __future__ import annotations

import contextlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.services.doc_modes.common import DOC_PIPELINE_UI_DEFAULTS
from app.services import multi_format


class MultiFormatWorkflowDefinitionTests(unittest.TestCase):
    def _create_values(self, **overrides: str) -> dict[str, str]:
        values = dict(DOC_PIPELINE_UI_DEFAULTS)
        values.update(overrides)
        return values

    def test_bookrag_table_groups_keep_core_indivisible_and_graph_all_or_nothing(self) -> None:
        flags = multi_format._resolve_bookrag_table_generation_flags(
            self._create_values(
                multi_format_bookrag_generate_documents="false",
                multi_format_bookrag_generate_blocks="false",
                multi_format_bookrag_generate_nodes="false",
                multi_format_bookrag_generate_raw="false",
                multi_format_bookrag_generate_graph="true",
            )
        )

        self.assertTrue(flags["documents"])
        self.assertTrue(flags["blocks"])
        self.assertTrue(flags["nodes"])
        self.assertFalse(flags["raw"])
        self.assertTrue(flags["entities"])
        self.assertTrue(flags["entity_links"])
        self.assertTrue(flags["entity_relations"])

    def test_bookrag_legacy_graph_toggle_enables_complete_graph_group(self) -> None:
        flags = multi_format._resolve_bookrag_table_generation_flags(
            self._create_values(
                multi_format_bookrag_generate_graph="false",
                multi_format_bookrag_generate_entity_links="true",
            )
        )

        self.assertTrue(flags["entities"])
        self.assertTrue(flags["entity_links"])
        self.assertTrue(flags["entity_relations"])

    def test_auto_defaults_keep_enrichments_disabled(self) -> None:
        request_parameters, warnings, processing_profile = multi_format._build_multi_format_workflow_definition(
            create_values=dict(DOC_PIPELINE_UI_DEFAULTS),
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
            ['Partitioner', 'Chunker'],
        )
        partition_node = request_parameters['workflow_nodes'][0]
        self.assertEqual(partition_node['subtype'], 'vlm')
        self.assertEqual(partition_node['settings']['strategy'], 'auto')
        self.assertNotIn('provider', partition_node['settings'])
        self.assertNotIn('model', partition_node['settings'])
        self.assertEqual(processing_profile, 'partition:vlm:auto,chunk:chunk_by_character')


    def test_hi_res_defaults_do_not_force_table_structure_or_block_extraction(self) -> None:
        request_parameters, warnings, processing_profile = multi_format._build_multi_format_workflow_definition(
            create_values=self._create_values(multi_format_strategy='hi_res'),
            src=Path('sample.pdf'),
            partition_strategy='hi_res',
            languages=['eng'],
            chunk_size=600,
            chunk_overlap=80,
            include_orig_elements=False,
            overlap_all=True,
        )

        self.assertEqual(warnings, [])
        partition_node = request_parameters['workflow_nodes'][0]
        self.assertEqual(partition_node['subtype'], 'unstructured_api')
        self.assertEqual(partition_node['settings']['strategy'], 'hi_res')
        self.assertNotIn('infer_table_structure', partition_node['settings'])
        self.assertNotIn('pdf_infer_table_structure', partition_node['settings'])
        self.assertNotIn('extract_image_block_types', partition_node['settings'])
        self.assertEqual(processing_profile, 'partition:unstructured_api:hi_res,chunk:chunk_by_character')

    def test_chunk_by_title_adds_title_only_settings(self) -> None:
        request_parameters, warnings, processing_profile = multi_format._build_multi_format_workflow_definition(
            create_values=self._create_values(
                multi_format_strategy='hi_res',
                multi_format_chunk_strategy='chunk_by_title',
                multi_format_chunk_new_after_n_chars='500',
                multi_format_chunk_combine_text_under_n_chars='200',
                multi_format_chunk_multipage_sections='false',
            ),
            src=Path('sample.pdf'),
            partition_strategy='hi_res',
            languages=['eng'],
            chunk_size=600,
            chunk_overlap=80,
            include_orig_elements=False,
            overlap_all=True,
        )

        self.assertEqual(warnings, [])
        chunk_node = request_parameters['workflow_nodes'][-1]
        self.assertEqual(chunk_node['subtype'], 'chunk_by_title')
        self.assertEqual(chunk_node['settings']['max_characters'], 600)
        self.assertEqual(chunk_node['settings']['new_after_n_chars'], 500)
        self.assertEqual(chunk_node['settings']['overlap'], 80)
        self.assertEqual(chunk_node['settings']['combine_text_under_n_chars'], 200)
        self.assertFalse(chunk_node['settings']['multipage_sections'])
        self.assertEqual(processing_profile, 'partition:unstructured_api:hi_res,chunk:chunk_by_title')

    def test_chunk_by_similarity_uses_similarity_threshold(self) -> None:
        request_parameters, warnings, processing_profile = multi_format._build_multi_format_workflow_definition(
            create_values=self._create_values(
                multi_format_chunk_strategy='chunk_by_similarity',
                multi_format_chunk_similarity_threshold='0.7',
            ),
            src=Path('sample.pdf'),
            partition_strategy='auto',
            languages=['eng'],
            chunk_size=600,
            chunk_overlap=80,
            include_orig_elements=False,
            overlap_all=True,
        )

        self.assertEqual(warnings, [])
        chunk_node = request_parameters['workflow_nodes'][-1]
        self.assertEqual(chunk_node['subtype'], 'chunk_by_similarity')
        self.assertEqual(chunk_node['settings']['max_characters'], 600)
        self.assertEqual(chunk_node['settings']['similarity_threshold'], 0.7)
        self.assertNotIn('overlap', chunk_node['settings'])
        self.assertEqual(processing_profile, 'partition:vlm:auto,chunk:chunk_by_similarity')

    def test_chunk_by_page_uses_page_chunk_settings(self) -> None:
        request_parameters, warnings, processing_profile = multi_format._build_multi_format_workflow_definition(
            create_values=self._create_values(
                multi_format_chunk_strategy='chunk_by_page',
                multi_format_chunk_new_after_n_chars='450',
            ),
            src=Path('sample.pdf'),
            partition_strategy='auto',
            languages=['eng'],
            chunk_size=600,
            chunk_overlap=80,
            include_orig_elements=False,
            overlap_all=True,
        )

        self.assertEqual(warnings, [])
        chunk_node = request_parameters['workflow_nodes'][-1]
        self.assertEqual(chunk_node['subtype'], 'chunk_by_page')
        self.assertEqual(chunk_node['settings']['max_characters'], 600)
        self.assertEqual(chunk_node['settings']['new_after_n_chars'], 450)
        self.assertEqual(chunk_node['settings']['overlap'], 80)
        self.assertTrue(chunk_node['settings']['overlap_all'])
        self.assertNotIn('combine_text_under_n_chars', chunk_node['settings'])
        self.assertNotIn('similarity_threshold', chunk_node['settings'])
        self.assertEqual(processing_profile, 'partition:vlm:auto,chunk:chunk_by_page')

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
            multi_format_infer_table_structure='true',
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
        partition_node = request_parameters['workflow_nodes'][0]
        self.assertEqual(partition_node['settings']['extract_image_block_types'], ['Table', 'Image'])
        self.assertTrue(partition_node['settings']['infer_table_structure'])
        self.assertTrue(partition_node['settings']['pdf_infer_table_structure'])
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
            multi_format_bookrag_enable_ner='true',
            multi_format_bookrag_image_description_subtype='openai_image_description',
            multi_format_bookrag_table_to_html_subtype='openai_table2html',
            multi_format_bookrag_table_description_subtype='openai_table_description',
            multi_format_bookrag_generative_ocr_subtype='openai_ocr',
            multi_format_bookrag_ner_subtype='openai_ner',
            multi_format_bookrag_ner_provider_type='openai',
            multi_format_bookrag_ner_model='gpt-4o-mini',
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
            ['Partitioner', 'Image Description', 'Table to HTML', 'Table Description', 'Generative OCR', 'Named Entity Recognition'],
        )
        self.assertEqual(workflow_nodes[0]['settings']['strategy'], 'hi_res')
        self.assertEqual(workflow_nodes[-1]['subtype'], 'openai_ner')
        self.assertEqual(workflow_nodes[-1]['settings']['provider_type'], 'openai')
        self.assertEqual(workflow_nodes[-1]['settings']['model'], 'gpt-4o-mini')
        self.assertIn('image_description', processing_profile)
        self.assertIn('generative_ocr', processing_profile)
        self.assertIn('ner:openai_ner', processing_profile)

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

    def test_bookrag_auto_partition_accepts_vlm_provider_settings(self) -> None:
        partition_node, _request_parameters, warnings = multi_format._build_bookrag_workflow_partition_node(
            src=Path('sample.pdf'),
            partition_strategy='auto',
            languages=[],
            image_partition_parameters={
                'vlm_provider': 'openai',
                'vlm_model': 'gpt-4o',
                'vlm_provider_api_key': 'secret-key',
                'unique_element_ids': True,
            },
        )

        self.assertEqual(warnings, [])
        self.assertEqual(partition_node['subtype'], 'vlm')
        self.assertEqual(partition_node['settings']['strategy'], 'auto')
        self.assertEqual(partition_node['settings']['provider'], 'openai')
        self.assertEqual(partition_node['settings']['model'], 'gpt-4o')
        self.assertEqual(partition_node['settings']['provider_api_key'], 'secret-key')

    def test_bookrag_ner_model_mismatch_drops_explicit_model(self) -> None:
        create_values = self._create_values(
            multi_format_bookrag_enable_ner='true',
            multi_format_bookrag_ner_subtype='openai_ner',
            multi_format_bookrag_ner_model='claude-sonnet-4-20250514',
        )
        _workflow_name, workflow_nodes, _request_parameters, warnings, _processing_profile = multi_format._build_bookrag_reusable_workflow_definition(
            create_values=create_values,
            partition_strategy='vlm',
            languages=[],
            image_partition_parameters={'unique_element_ids': True},
        )

        ner_node = workflow_nodes[-1]
        self.assertEqual(ner_node['name'], 'Named Entity Recognition')
        self.assertEqual(ner_node['subtype'], 'openai_ner')
        self.assertEqual(ner_node['settings']['provider_type'], 'openai')
        self.assertNotIn('model', ner_node['settings'])
        self.assertTrue(any('does not match subtype' in warning for warning in warnings))

    def test_bookrag_image_partition_options_read_bookrag_overrides(self) -> None:
        options, warnings, summary = multi_format._resolve_bookrag_image_partition_options(
            self._create_values(
                multi_format_bookrag_extract_image_block_types='Image,Table',
                multi_format_bookrag_infer_table_structure='true',
                multi_format_bookrag_hi_res_model_name='layout-v2',
                multi_format_bookrag_vlm_provider='openai',
                multi_format_bookrag_vlm_model='gpt-4o',
                multi_format_bookrag_vlm_provider_api_key='secret-key',
                multi_format_bookrag_coordinates='false',
            )
        )

        self.assertEqual(warnings, [])
        self.assertEqual(options['extract_image_block_types'], ['Image', 'Table'])
        self.assertTrue(options['infer_table_structure'])
        self.assertEqual(options['hi_res_model_name'], 'layout-v2')
        self.assertEqual(options['vlm_provider'], 'openai')
        self.assertEqual(options['vlm_model'], 'gpt-4o')
        self.assertEqual(options['vlm_provider_api_key'], 'secret-key')
        self.assertFalse(options['coordinates'])
        self.assertEqual(summary['vlm_provider'], 'openai')
        self.assertEqual(summary['vlm_model'], 'gpt-4o')
        self.assertTrue(summary['vlm_provider_api_key_configured'])

    def test_multi_format_definition_ignores_bookrag_namespaced_inputs(self) -> None:
        create_values = self._create_values(
            multi_format_strategy='auto',
            multi_format_bookrag_vlm_provider='openai',
            multi_format_bookrag_vlm_model='gpt-4o',
            multi_format_bookrag_enable_image_description='true',
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
            ['Partitioner', 'Chunker'],
        )
        partition_node = request_parameters['workflow_nodes'][0]
        self.assertNotIn('provider', partition_node['settings'])
        self.assertNotIn('model', partition_node['settings'])
        self.assertEqual(processing_profile, 'partition:vlm:auto,chunk:chunk_by_character')

    def test_as_text_strips_invalid_unicode_for_teradata(self) -> None:
        raw = "A\x00B\ud800C\ufdd0D\ufffeE🆓\nF\tG"
        self.assertEqual(multi_format._as_text(raw), "ABCDE\nF\tG")

    def test_insert_chunk_rows_omits_invalid_unicode_from_sql_literals(self) -> None:
        executed: list[str] = []

        rows = [
            {
                "text": multi_format._as_text("Hello\x00World\ud800"),
                "type": "NarrativeText",
                "filename": "demo.pdf",
                "element_id": "el-1",
                "id": "000000000001",
                "table_id": None,
                "chunk_index": 1,
                "is_continuation": False,
                "num_carried_over_header_rows": None,
                "partitioner_type": "vlm",
                "image_description": multi_format._as_text("img\ufffe"),
                "table_description": None,
                "generative_ocr": None,
                "table_to_html": None,
                "filetype": "application/pdf",
                "date_processed": "2026-05-27 00:00:00",
            }
        ]

        inserted = multi_format._insert_chunk_rows(
            schema_name=None,
            table_name="demo_unstructured",
            rows=rows,
            execute_sql_fn=executed.append,
        )

        self.assertEqual(inserted, 1)
        self.assertEqual(len(executed), 1)
        sql = executed[0]
        self.assertIn("HelloWorld", sql)
        self.assertIn("img", sql)
        self.assertNotIn("\x00", sql)
        self.assertNotIn("\ud800", sql)
        self.assertNotIn("\ufffe", sql)

    def test_bookrag_image_partition_options_ignore_multi_format_inputs(self) -> None:
        options, warnings, summary = multi_format._resolve_bookrag_image_partition_options(
            self._create_values(
                multi_format_extract_image_block_types='Image,Table',
                multi_format_infer_table_structure='true',
                multi_format_hi_res_model_name='layout-v2',
                multi_format_vlm_provider='openai',
                multi_format_vlm_model='gpt-4o',
                multi_format_vlm_provider_api_key='secret-key',
            )
        )

        self.assertEqual(options['extract_image_block_types'], ['Image', 'Table'])
        self.assertFalse(options['infer_table_structure'])
        self.assertNotIn('hi_res_model_name', options)
        self.assertIsNone(options['vlm_provider'])
        self.assertIsNone(options['vlm_model'])
        self.assertIsNone(options['vlm_provider_api_key'])
        self.assertTrue(options['coordinates'])
        self.assertEqual(warnings, [])
        self.assertIsNone(summary['hi_res_model_name'])
        self.assertIsNone(summary['vlm_provider'])
        self.assertIsNone(summary['vlm_model'])
        self.assertFalse(summary['vlm_provider_api_key_configured'])

    def test_generic_runtime_defaults_do_not_cross_between_modes(self) -> None:
        shared_runtime = {
            'infer_table_structure': 'true',
            'hi_res_model_name': 'shared-layout',
            'vlm_provider': 'openai',
            'vlm_model': 'gpt-4o',
            'vlm_provider_api_key': 'shared-secret',
            'extract_image_block_types': 'Image,Table',
            'unique_element_ids': 'false',
        }
        with mock.patch('app.services.multi_format._load_unstructured_runtime_settings', return_value=shared_runtime):
            bookrag_options, bookrag_warnings, _summary = multi_format._resolve_bookrag_image_partition_options(self._create_values())
            request_parameters, workflow_warnings, _profile = multi_format._build_multi_format_workflow_definition(
                create_values=self._create_values(multi_format_strategy='hi_res'),
                src=Path('sample.pdf'),
                partition_strategy='hi_res',
                languages=['eng'],
                chunk_size=600,
                chunk_overlap=80,
                include_orig_elements=False,
                overlap_all=True,
            )

        self.assertEqual(workflow_warnings, [])
        partition_node = request_parameters['workflow_nodes'][0]
        self.assertNotIn('infer_table_structure', partition_node['settings'])
        self.assertNotIn('hi_res_model_name', partition_node['settings'])
        self.assertNotIn('provider', partition_node['settings'])
        self.assertNotIn('model', partition_node['settings'])
        self.assertEqual(bookrag_options['extract_image_block_types'], ['Image', 'Table'])
        self.assertFalse(bookrag_options['infer_table_structure'])
        self.assertTrue(bookrag_options['unique_element_ids'])
        self.assertIsNone(bookrag_options['vlm_provider'])
        self.assertIsNone(bookrag_options['vlm_model'])
        self.assertIsNone(bookrag_options['vlm_provider_api_key'])
        self.assertEqual(bookrag_warnings, [])

    def test_chunk_rows_use_sequence_ids_and_map_selected_metadata(self) -> None:
        row = multi_format._element_to_chunk_row(
            {
                'id': 'unstructured-element-7',
                'element_id': 'unstructured-element-7',
                'type': 'TableChunk',
                'text': 'chunk text',
                'metadata': {
                    'filename': 'demo.pdf',
                    'table_id': 'table-1',
                    'page_number': 3,
                    'chunk_index': 3,
                    'is_continuation': True,
                    'num_carried_over_header_rows': 2,
                    'partitioner_type': 'hi_res_partition',
                    'image_description': 'image summary',
                    'table_description': 'table summary',
                    'generative_ocr': 'ocr text',
                    'text_as_html': '<table><tr><td>x</td></tr></table>',
                },
            },
            src=Path(__file__),
            content_type='application/pdf',
            row_sequence=7,
        )

        self.assertIsNotNone(row)
        self.assertEqual(row['id'], '000000000007')
        self.assertEqual(row['element_id'], 'unstructured-element-7')
        self.assertEqual(row['filename'], 'demo.pdf')
        self.assertEqual(row['table_id'], 'table-1')
        self.assertEqual(row['page_number'], 3)
        self.assertEqual(row['chunk_index'], 3)
        self.assertTrue(row['is_continuation'])
        self.assertEqual(row['num_carried_over_header_rows'], 2)
        self.assertEqual(row['partitioner_type'], 'hi_res_partition')
        self.assertEqual(row['image_description'], 'image summary')
        self.assertEqual(row['table_description'], 'table summary')
        self.assertEqual(row['generative_ocr'], 'ocr text')
        self.assertEqual(row['text_as_html'], '<table><tr><td>x</td></tr></table>')
        self.assertEqual(row['table_to_html'], '<table><tr><td>x</td></tr></table>')
        self.assertNotIn('record_id', row)
        self.assertNotIn('parent_id', row)

    def test_chunk_row_keeps_page_and_does_not_treat_narrative_html_as_table_html(self) -> None:
        row = multi_format._element_to_chunk_row(
            {
                'element_id': 'element-1',
                'type': 'CompositeElement',
                'text': 'body text',
                'metadata': {
                    'filename': 'demo.pdf',
                    'page_number': 11,
                    'text_as_html': '<p>body text</p>',
                    'table_to_html': '<table><tr><td>not a table element</td></tr></table>',
                },
            },
            src=Path('fallback.pdf'),
            content_type='application/pdf',
            row_sequence=8,
        )

        self.assertIsNotNone(row)
        self.assertEqual(row['page_number'], 11)
        self.assertEqual(row['text_as_html'], '<p>body text</p>')
        self.assertIsNone(row['table_to_html'])

    def test_chunk_row_filename_uses_unstructured_metadata_filename(self) -> None:
        src = Path('A S 茜町（異動2019.01.30）.pdf')
        row = multi_format._element_to_chunk_row(
            {
                'element_id': 'element-1',
                'type': 'NarrativeText',
                'text': 'body text',
                'metadata': {
                    'filename': 'AS茜町異動20190130-c4dcc7ff.pdf',
                    'filetype': 'application/pdf',
                },
            },
            src=src,
            content_type='application/pdf',
            row_sequence=1,
        )

        self.assertIsNotNone(row)
        self.assertEqual(row['filename'], 'AS茜町異動20190130-c4dcc7ff.pdf')

    def test_bookrag_document_and_root_node_keep_source_file_name(self) -> None:
        from app.services.bookrag_storage import build_bookrag_document_row
        from app.services.bookrag_tree import build_bookrag_nodes

        src = Path('A S 茜町（異動2019.01.30）.pdf')
        document_row = build_bookrag_document_row(
            doc_id='doc-1',
            vector_store_name='demo',
            workflow_id='workflow-1',
            workflow_name='BookRAG_Test',
            job_id='job-1',
            processing_profile='partition:vlm:vlm',
            filename=src.name,
            source_file='raw_stage/AS_20190130_doc-1.json',
            filetype='application/pdf',
            filesize_bytes=123,
        )
        nodes = build_bookrag_nodes(document_row, [])

        self.assertEqual(document_row['filename'], src.name)
        self.assertEqual(nodes[0]['title'], src.name)
        self.assertEqual(nodes[0]['path'], src.name)



    def test_bookrag_pipeline_bypasses_reconcile_for_entities(self) -> None:
        create_values = self._create_values(
            multi_format_bookrag_generate_entities='true',
            multi_format_bookrag_generate_entity_links='true',
            multi_format_bookrag_generate_entity_relations='true',
        )
        raw_payload = [
            {
                'type': 'NarrativeText',
                'element_id': 'raw-1',
                'text': 'Raw payload without entities.',
                'metadata': {
                    'page_number': 1,
                    'category_depth': 1,
                },
            },
        ]
        reconciled_payload = [
            {
                'type': 'NarrativeText',
                'element_id': 'recon-1',
                'text': 'Reconciled payload with entities.',
                'metadata': {
                    'page_number': 1,
                    'category_depth': 1,
                    'entities': {
                        'items': [
                            {'entity': 'Demo Corp', 'type': 'ORGANIZATION'},
                        ],
                        'relationships': [
                            {'from': 'Demo Corp', 'relationship': 'published_in', 'to': '2026-04-18'},
                        ],
                    },
                },
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            src = tmp_path / 'sample.txt'
            src.write_text('demo', encoding='utf-8')
            debug_dir = tmp_path / 'debug'
            raw_stage_dir = tmp_path / 'raw_stage'
            csv_stage_dir = tmp_path / 'csv_stage'

            captured: dict[str, object] = {}

            def _persist_nodes(*, nodes, **kwargs):
                captured['nodes'] = nodes
                return len(nodes)

            def _persist_entities(*, entities, **kwargs):
                captured['entities'] = entities
                return len(entities)

            def _persist_entity_links(*, entity_links, **kwargs):
                captured['entity_links'] = entity_links
                return len(entity_links)

            def _persist_entity_relations(*, entity_relations, **kwargs):
                captured['entity_relations'] = entity_relations
                return len(entity_relations)

            with contextlib.ExitStack() as stack:
                stack.enter_context(mock.patch('app.services.multi_format.prepare_bookrag_document_table', return_value=[]))
                stack.enter_context(mock.patch('app.services.multi_format.prepare_bookrag_block_table', return_value=[]))
                stack.enter_context(mock.patch('app.services.multi_format.prepare_bookrag_node_table', return_value=[]))
                stack.enter_context(mock.patch('app.services.multi_format.prepare_bookrag_document_relation_table', return_value=[]))
                stack.enter_context(mock.patch('app.services.multi_format.prepare_bookrag_entity_table', return_value=[]))
                stack.enter_context(mock.patch('app.services.multi_format.prepare_bookrag_entity_link_table', return_value=[]))
                stack.enter_context(mock.patch('app.services.multi_format.prepare_bookrag_entity_relation_table', return_value=[]))
                stack.enter_context(mock.patch('app.services.multi_format.prepare_bookrag_raw_table', return_value=[]))
                stack.enter_context(mock.patch('app.services.multi_format._load_unstructured_runtime_config', return_value=('key', 'https://example.invalid')))
                stack.enter_context(mock.patch('app.services.multi_format._resolve_unstructured_request_timeout_ms', return_value=120000))
                stack.enter_context(mock.patch('app.services.multi_format._create_unstructured_client', return_value=object()))
                stack.enter_context(mock.patch('app.services.multi_format._prepare_unstructured_debug_dir', return_value=debug_dir))
                stack.enter_context(mock.patch('app.services.multi_format._prepare_bookrag_raw_stage_dir', return_value=raw_stage_dir))
                stack.enter_context(mock.patch('app.services.multi_format._prepare_bookrag_csv_stage_dir', return_value=csv_stage_dir))
                stack.enter_context(mock.patch('app.services.multi_format._resolve_bookrag_workflow_poll_config', return_value=(30, 1)))
                stack.enter_context(mock.patch('app.services.multi_format._enforce_unstructured_job_submission_spacing', side_effect=lambda value: value))
                stack.enter_context(mock.patch('app.services.multi_format._build_bookrag_reusable_workflow_definition', return_value=('BookRAG_Test', [{'name': 'Partitioner'}], {'workflow_name': 'BookRAG_Test', 'workflow_nodes': [{'name': 'Partitioner'}]}, [], 'partition:vlm:vlm')))
                stack.enter_context(mock.patch('app.services.multi_format._run_unstructured_workflow_job_for_file', return_value=(raw_payload, raw_payload, {'workflow_name': 'BookRAG_Test'}, 'job-1', 'workflow-1', 'BookRAG_Test')))
                reconcile_mock = stack.enter_context(mock.patch('app.services.multi_format.reconcile_unstructured_elements', return_value=reconciled_payload))
                stack.enter_context(mock.patch('app.services.multi_format._write_unstructured_debug_file', return_value=''))
                stack.enter_context(mock.patch('app.services.multi_format.persist_bookrag_documents', return_value=1))
                stack.enter_context(mock.patch('app.services.multi_format.persist_bookrag_raw_rows', return_value=1))
                stack.enter_context(mock.patch('app.services.multi_format.persist_bookrag_blocks', return_value=1))
                stack.enter_context(mock.patch('app.services.multi_format.persist_bookrag_nodes', side_effect=_persist_nodes))
                stack.enter_context(mock.patch('app.services.multi_format.persist_bookrag_entities', side_effect=_persist_entities))
                stack.enter_context(mock.patch('app.services.multi_format.persist_bookrag_entity_links', side_effect=_persist_entity_links))
                stack.enter_context(mock.patch('app.services.multi_format.persist_bookrag_entity_relations', side_effect=_persist_entity_relations))
                stack.enter_context(mock.patch('app.services.multi_format._count_teradata_rows', return_value=1))
                _, summary = multi_format._apply_bookrag_tree_pipeline(
                    exec_payload={
                        'document_files': [str(src)],
                        'nv_ingestor': 'legacy-file-ingestor',
                        'custom_ingestor': 'legacy-custom-ingestor',
                        'ingest_host': 'legacy-host',
                    },
                    create_values=create_values,
                    vector_store_name='demo',
                    execute_sql_fn=mock.Mock(),
                    resolve_path_hint=lambda value: value,
                    effective_schema_name='demo_schema',
                    document_files=[str(src)],
                    partition_strategy='vlm',
                    ocr_languages=['jpn'],
                    target_warnings=[],
                )

        reconcile_mock.assert_not_called()
        self.assertEqual(summary['entity_count'], 0)
        self.assertEqual(summary['entity_link_count'], 0)
        self.assertEqual(summary['entity_relation_count'], 0)
        self.assertEqual(captured['nodes'][1]['source_element_id'], 'raw-1')
        self.assertEqual(captured['entities'], [])
        self.assertEqual(captured['entity_links'], [])
        self.assertEqual(captured['entity_relations'], [])

    def test_bookrag_pipeline_persists_tree_outputs(self) -> None:
        create_values = self._create_values(
            multi_format_bookrag_generate_entities='true',
            multi_format_bookrag_generate_entity_links='true',
            multi_format_bookrag_generate_entity_relations='true',
        )
        raw_payload = [
            {
                'type': 'Title',
                'element_id': 'title-1',
                'text': 'Section Overview',
                'metadata': {
                    'page_number': 1,
                    'category_depth': 2,
                    'parent_id': 'section-1',
                },
            },
            {
                'type': 'NarrativeText',
                'element_id': 'text-1',
                'text': 'This is the body text.',
                'metadata': {
                    'page_number': 1,
                    'category_depth': 2,
                    'parent_id': 'section-1',
                    'entities': {
                        'items': [
                            {'entity': 'Demo Corp', 'type': 'ORGANIZATION'},
                            {'entity': '2026-04-18', 'type': 'DATE'},
                        ],
                        'relationships': [
                            {'from': 'Demo Corp', 'relationship': 'published_in', 'to': '2026-04-18'},
                        ],
                    },
                },
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            src = tmp_path / 'sample.txt'
            src.write_text('demo', encoding='utf-8')
            raw_stage_dir = tmp_path / 'raw_stage'
            csv_stage_dir = tmp_path / 'csv_stage'
            debug_dir = tmp_path / 'debug'

            captured: dict[str, object] = {}

            def _persist_documents(*, rows, **kwargs):
                captured['document_rows'] = rows
                return len(rows)

            def _persist_raw(*, rows, **kwargs):
                captured['raw_rows'] = rows
                return len(rows)

            def _persist_blocks(*, blocks, **kwargs):
                captured['blocks'] = blocks
                return len(blocks)

            def _persist_nodes(*, nodes, **kwargs):
                captured['nodes'] = nodes
                return len(nodes)

            def _persist_entities(*, entities, **kwargs):
                captured['entities'] = entities
                return len(entities)

            def _persist_entity_links(*, entity_links, **kwargs):
                captured['entity_links'] = entity_links
                return len(entity_links)

            def _persist_entity_relations(*, entity_relations, **kwargs):
                captured['entity_relations'] = entity_relations
                return len(entity_relations)

            with contextlib.ExitStack() as stack:
                stack.enter_context(mock.patch('app.services.multi_format.prepare_bookrag_document_table', return_value=[]))
                stack.enter_context(mock.patch('app.services.multi_format.prepare_bookrag_block_table', return_value=[]))
                stack.enter_context(mock.patch('app.services.multi_format.prepare_bookrag_node_table', return_value=[]))
                stack.enter_context(mock.patch('app.services.multi_format.prepare_bookrag_document_relation_table', return_value=[]))
                stack.enter_context(mock.patch('app.services.multi_format.prepare_bookrag_entity_table', return_value=[]))
                stack.enter_context(mock.patch('app.services.multi_format.prepare_bookrag_entity_link_table', return_value=[]))
                stack.enter_context(mock.patch('app.services.multi_format.prepare_bookrag_entity_relation_table', return_value=[]))
                stack.enter_context(mock.patch('app.services.multi_format.prepare_bookrag_raw_table', return_value=[]))
                stack.enter_context(mock.patch('app.services.multi_format._load_unstructured_runtime_config', return_value=('key', 'https://example.invalid')))
                stack.enter_context(mock.patch('app.services.multi_format._resolve_unstructured_request_timeout_ms', return_value=120000))
                stack.enter_context(mock.patch('app.services.multi_format._create_unstructured_client', return_value=object()))
                stack.enter_context(mock.patch('app.services.multi_format._prepare_unstructured_debug_dir', return_value=debug_dir))
                stack.enter_context(mock.patch('app.services.multi_format._prepare_bookrag_raw_stage_dir', return_value=raw_stage_dir))
                stack.enter_context(mock.patch('app.services.multi_format._prepare_bookrag_csv_stage_dir', return_value=csv_stage_dir))
                stack.enter_context(mock.patch('app.services.multi_format._resolve_bookrag_workflow_poll_config', return_value=(30, 1)))
                stack.enter_context(mock.patch('app.services.multi_format._enforce_unstructured_job_submission_spacing', side_effect=lambda value: value))
                stack.enter_context(mock.patch('app.services.multi_format._build_bookrag_reusable_workflow_definition', return_value=('BookRAG_Test', [{'name': 'Partitioner'}], {'workflow_name': 'BookRAG_Test', 'workflow_nodes': [{'name': 'Partitioner'}]}, [], 'partition:vlm:vlm')))
                stack.enter_context(mock.patch('app.services.multi_format._run_unstructured_workflow_job_for_file', return_value=(raw_payload, raw_payload, {'workflow_name': 'BookRAG_Test'}, 'job-1', 'workflow-1', 'BookRAG_Test')))
                stack.enter_context(mock.patch('app.services.multi_format._write_unstructured_debug_file', return_value=''))
                stack.enter_context(mock.patch('app.services.multi_format.persist_bookrag_documents', side_effect=_persist_documents))
                stack.enter_context(mock.patch('app.services.multi_format.persist_bookrag_raw_rows', side_effect=_persist_raw))
                stack.enter_context(mock.patch('app.services.multi_format.persist_bookrag_blocks', side_effect=_persist_blocks))
                stack.enter_context(mock.patch('app.services.multi_format.persist_bookrag_nodes', side_effect=_persist_nodes))
                stack.enter_context(mock.patch('app.services.multi_format.persist_bookrag_entities', side_effect=_persist_entities))
                stack.enter_context(mock.patch('app.services.multi_format.persist_bookrag_entity_links', side_effect=_persist_entity_links))
                stack.enter_context(mock.patch('app.services.multi_format.persist_bookrag_entity_relations', side_effect=_persist_entity_relations))
                stack.enter_context(mock.patch('app.services.multi_format._count_teradata_rows', return_value=len(raw_payload)))
                patched_payload, summary = multi_format._apply_bookrag_tree_pipeline(
                    exec_payload={
                        'document_files': [str(src)],
                        'document_manifest': [
                            {
                                'doc_id': 'upload-doc-id',
                                'filename': src.name,
                                'saved_path': str(src),
                            }
                        ],
                    },
                    create_values=create_values,
                    vector_store_name='demo',
                    execute_sql_fn=mock.Mock(),
                    resolve_path_hint=lambda value: value,
                    effective_schema_name='demo_schema',
                    document_files=[str(src)],
                    partition_strategy='vlm',
                    ocr_languages=['jpn'],
                    target_warnings=[],
                )

        self.assertEqual(summary['workflow_mode'], 'bookrag on-demand jobs selected tables debug')
        self.assertEqual(summary['raw_element_count'], 2)
        self.assertEqual(summary['block_count'], 2)
        self.assertEqual(summary['node_count'], 3)
        self.assertEqual(summary['entity_count'], 2)
        self.assertEqual(summary['entity_link_count'], 2)
        self.assertEqual(summary['entity_relation_count'], 1)
        self.assertEqual(summary['bookrag_chunking_strategy'], 'disabled_for_tree_debug')
        self.assertEqual(patched_payload['object_names'], 'demo_schema.demo_bk_bnode')
        self.assertEqual(patched_payload['data_columns'], ['content'])
        self.assertEqual(patched_payload['key_columns'], ['doc_id', 'node_id'])
        self.assertNotIn('vector_column', patched_payload)
        self.assertNotIn('document_files', patched_payload)
        self.assertNotIn('nv_ingestor', patched_payload)
        self.assertNotIn('custom_ingestor', patched_payload)
        self.assertNotIn('ingest_host', patched_payload)
        self.assertIn('unstructured_bookrag_flg', patched_payload['description'])
        self.assertEqual(summary['vectorstore_source_object'], 'demo_schema.demo_bk_bnode')
        self.assertEqual(len(captured['document_rows']), 1)
        self.assertEqual(captured['document_rows'][0]['doc_id'], 'upload-doc-id')
        self.assertEqual(len(captured['raw_rows']), 2)
        self.assertEqual(len(captured['blocks']), 2)
        self.assertEqual(len(captured['nodes']), 3)
        self.assertEqual(len(captured['entities']), 2)
        self.assertEqual(len(captured['entity_links']), 2)
        self.assertEqual(len(captured['entity_relations']), 1)
        self.assertEqual(summary['bookrag_csv_stage_dir'], str(csv_stage_dir))
        self.assertEqual(summary['bookrag_csv_stage_files'], [])


    def test_bookrag_pipeline_flushes_after_file_threshold(self) -> None:
        create_values = self._create_values()
        raw_payload_by_name = {
            'sample1.txt': [
                {
                    'type': 'NarrativeText',
                    'element_id': 'text-1',
                    'text': 'First document text.',
                    'metadata': {'page_number': 1},
                },
            ],
            'sample2.txt': [
                {
                    'type': 'NarrativeText',
                    'element_id': 'text-2',
                    'text': 'Second document text.',
                    'metadata': {'page_number': 1},
                },
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            sources = [tmp_path / 'sample1.txt', tmp_path / 'sample2.txt']
            for src in sources:
                src.write_text('demo', encoding='utf-8')
            raw_stage_dir = tmp_path / 'raw_stage'
            csv_stage_dir = tmp_path / 'csv_stage'
            debug_dir = tmp_path / 'debug'
            document_batch_sizes: list[int] = []
            document_csv_dirs: list[Path] = []
            raw_batch_sizes: list[int] = []
            block_batch_sizes: list[int] = []
            node_batch_sizes: list[int] = []
            document_relation_rows: list[dict] = []

            def _run_job(client=None, *, src, **kwargs):
                payload = raw_payload_by_name[src.name]
                return payload, payload, {'workflow_name': 'BookRAG_Test'}, f'job-{src.stem}', 'workflow-1', 'BookRAG_Test'

            def _persist_documents(*, rows, csv_stage_dir=None, **kwargs):
                document_batch_sizes.append(len(rows))
                document_csv_dirs.append(Path(csv_stage_dir))
                return len(rows)

            def _persist_raw(*, rows, **kwargs):
                raw_batch_sizes.append(len(rows))
                return len(rows)

            def _persist_blocks(*, blocks, **kwargs):
                block_batch_sizes.append(len(blocks))
                return len(blocks)

            def _persist_nodes(*, nodes, **kwargs):
                node_batch_sizes.append(len(nodes))
                return len(nodes)

            def _suggest_relations(documents):
                newer, older = documents
                return [
                    {
                        "from_doc_id": newer["doc_id"],
                        "from_filename": newer["filename"],
                        "relation_type": "next_issue_of",
                        "to_doc_id": older["doc_id"],
                        "to_filename": older["filename"],
                        "relation_description": "Filename rule created an initial relationship.",
                        "source_type": "rule",
                        "confidence": 1.0,
                        "is_active": 0,
                        "confirmed": False,
                    }
                ]

            def _persist_relations(*, relations, **kwargs):
                document_relation_rows.extend(relations)
                return len(relations)

            with contextlib.ExitStack() as stack:
                stack.enter_context(mock.patch.dict('os.environ', {'BOOKRAG_UNSTRUCTURED_WORKERS': '2'}))
                stack.enter_context(mock.patch('app.services.multi_format.prepare_bookrag_document_table', return_value=[]))
                stack.enter_context(mock.patch('app.services.multi_format.prepare_bookrag_block_table', return_value=[]))
                stack.enter_context(mock.patch('app.services.multi_format.prepare_bookrag_node_table', return_value=[]))
                stack.enter_context(mock.patch('app.services.multi_format.prepare_bookrag_document_relation_table', return_value=[]))
                stack.enter_context(mock.patch('app.services.multi_format.prepare_bookrag_raw_table', return_value=[]))
                stack.enter_context(mock.patch('app.services.multi_format._load_unstructured_runtime_config', return_value=('key', 'https://example.invalid')))
                stack.enter_context(mock.patch('app.services.multi_format._resolve_unstructured_request_timeout_ms', return_value=120000))
                stack.enter_context(mock.patch('app.services.multi_format._create_unstructured_client', return_value=object()))
                stack.enter_context(mock.patch('app.services.multi_format._prepare_unstructured_debug_dir', return_value=debug_dir))
                stack.enter_context(mock.patch('app.services.multi_format._prepare_bookrag_raw_stage_dir', return_value=raw_stage_dir))
                stack.enter_context(mock.patch('app.services.multi_format._prepare_bookrag_csv_stage_dir', return_value=csv_stage_dir))
                stack.enter_context(mock.patch('app.services.multi_format._resolve_bookrag_workflow_poll_config', return_value=(30, 1)))
                stack.enter_context(mock.patch('app.services.multi_format._enforce_unstructured_job_submission_spacing', side_effect=lambda value: value))
                stack.enter_context(mock.patch('app.services.multi_format._build_bookrag_reusable_workflow_definition', return_value=('BookRAG_Test', [{'name': 'Partitioner'}], {'workflow_name': 'BookRAG_Test', 'workflow_nodes': [{'name': 'Partitioner'}]}, [], 'partition:vlm:vlm')))
                stack.enter_context(mock.patch('app.services.multi_format._run_unstructured_workflow_job_for_file', side_effect=_run_job))
                stack.enter_context(mock.patch('app.services.multi_format._write_unstructured_debug_file', return_value=''))
                stack.enter_context(mock.patch('app.services.multi_format.persist_bookrag_documents', side_effect=_persist_documents))
                stack.enter_context(mock.patch('app.services.multi_format.persist_bookrag_raw_rows', side_effect=_persist_raw))
                stack.enter_context(mock.patch('app.services.multi_format.persist_bookrag_blocks', side_effect=_persist_blocks))
                stack.enter_context(mock.patch('app.services.multi_format.persist_bookrag_nodes', side_effect=_persist_nodes))
                stack.enter_context(mock.patch('app.services.multi_format.suggest_document_relations', side_effect=_suggest_relations))
                stack.enter_context(mock.patch('app.services.multi_format.persist_document_relations', side_effect=_persist_relations))
                stack.enter_context(mock.patch('app.services.multi_format._count_teradata_rows', return_value=2))

                _, summary = multi_format._apply_bookrag_tree_pipeline(
                    exec_payload={'document_files': [str(src) for src in sources]},
                    create_values=create_values,
                    vector_store_name='demo',
                    execute_sql_fn=mock.Mock(),
                    resolve_path_hint=lambda value: value,
                    effective_schema_name='demo_schema',
                    document_files=[str(src) for src in sources],
                    partition_strategy='vlm',
                    ocr_languages=['jpn'],
                    target_warnings=[],
                )

        self.assertEqual(summary['document_count'], 2)
        self.assertEqual(summary['bookrag_flush_config'], {'mode': 'per_file'})
        self.assertEqual(summary['bookrag_flush_count'], 2)
        self.assertEqual(summary['bookrag_unstructured_workers'], 2)
        self.assertEqual(len(set(document_csv_dirs)), 2)
        self.assertTrue(all(path.parent == csv_stage_dir for path in document_csv_dirs))
        self.assertEqual([batch['reason'] for batch in summary['bookrag_flush_batches']], ['file_ready', 'file_ready'])
        self.assertEqual(document_batch_sizes, [1, 1])
        self.assertEqual(raw_batch_sizes, [1, 1])
        self.assertEqual(block_batch_sizes, [1, 1])
        self.assertEqual(node_batch_sizes, [2, 2])
        self.assertEqual(summary['document_relation_count'], 1)
        self.assertEqual(summary['document_relation_rule_count'], 1)
        self.assertEqual(len(document_relation_rows), 1)
        self.assertEqual(document_relation_rows[0]['is_active'], 0)
        self.assertTrue(document_relation_rows[0]['confirmed'])


if __name__ == '__main__':
    unittest.main()
