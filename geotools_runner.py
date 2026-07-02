# -*- coding: utf-8 -*-

import importlib

from .add_sets_layers import add_csv_vector_layer
from .geotools_config import ExecutionLog, normalize_config
from .merge_features_in_polygon import merge_visible_features_in_selected_polygon
from .ward_boundary_buffer import ward_boundary_buffer_frame


class ConfigurableToolRunner:
    """Dispatch JSON configs to the existing koji GeoTools implementations."""

    def __init__(self, iface):
        self.iface = iface

    def run(self, config):
        normalized = normalize_config(config)
        log = ExecutionLog()
        tool = normalized['tool']
        log.info('Start tool: {0}'.format(tool))

        try:
            if tool == 'add_sets_layers':
                result = self._run_layer_sets(normalized, log)
            elif tool == 'ward_boundary_buffer':
                result = self._run_ward_boundary_buffer(normalized, log)
            elif tool == 'merge_features_in_polygon':
                result = self._run_merge_features(normalized, log)
            else:
                raise ValueError('Unsupported tool: {0}'.format(tool))

            log.info('Finished tool: {0}'.format(tool))
            log.save_if_requested(normalized)
            return result, log
        except Exception as exc:
            log.error(str(exc))
            log.save_if_requested(normalized)
            raise

    def _run_layer_sets(self, config, log):
        layer_sets = config.get('layer_sets') or {}
        input_config = config.get('input') or {}
        output_config = config.get('output') or {}
        layer_configs = config.get('layers') or layer_sets.get('layers')
        if layer_configs:
            result = add_csv_vector_layer.run_configured_layers(
                iface=self.iface,
                csv_path=input_config.get('csv_path') or '',
                output_path=output_config.get('gpkg_path') or '',
                x_field=input_config.get('x_field') or '世界_10進_X',
                y_field=input_config.get('y_field') or '世界_10進_Y',
                crs=output_config.get('crs') or input_config.get('crs') or 'EPSG:4326',
                layer_configs=layer_configs,
                add_to_project=output_config.get('add_to_project', True),
            )
            log.info('Configured layer set result: {0}'.format(result))
            return result

        if output_config.get('gpkg_path'):
            log.warning('Layer-set GeoPackage export needs layers config; using the legacy project-layer workflow.')

        result = add_csv_vector_layer.run_main(
            iface=self.iface,
            csv_path=input_config.get('csv_path') or None,
            selected_ward=layer_sets.get('selected_ward') or None,
            shape=layer_sets.get('shape') or None,
            size_mm=layer_sets.get('size_mm'),
            group_selection=layer_sets.get('group_selection') or 'group1',
            area_filter=layer_sets.get('area_filter') or None,
        )
        log.info('Layer set result: {0}'.format(result))
        return result

    def _run_ward_boundary_buffer(self, config, log):
        geometry = config.get('geometry') or {}
        buffer_distance_m = geometry.get('buffer_distance_m')
        if buffer_distance_m not in (None, 2000):
            log.warning('Custom buffer distance is recorded in config but the interactive workflow currently uses its dialog value.')
        if geometry.get('dissolve') is False:
            log.warning('Dissolve=false is recorded in config but the legacy workflow currently dissolves output.')
        result = ward_boundary_buffer_frame.run_ward_boundary_buffer(self.iface)
        log.info('Ward boundary buffer workflow finished.')
        return result

    def _run_merge_features(self, config, log):
        importlib.reload(merge_visible_features_in_selected_polygon)
        merge_config = config.get('merge') or {}
        output_config = config.get('output') or {}
        result = merge_visible_features_in_selected_polygon.run_merge_visible_features_in_selected_polygon(
            self.iface,
            output_path=output_config.get('gpkg_path') or None,
            output_layer_name=output_config.get('layer_name') or None,
            output_polygon_layer_name=output_config.get('polygon_layer_name') or None,
            output_crs=output_config.get('crs') or None,
            add_to_project=output_config.get('add_to_project', True),
            add_source_fid=merge_config.get('add_source_fid', True),
            inherit_style=merge_config.get('inherit_style', True),
            layer_group_name=output_config.get('layer_group_name') or '',
            output_mode=merge_config.get('output_mode') or 'single',
            name_prefix=merge_config.get('name_prefix') or '',
        )
        log.info('Merged features result: {0}'.format(result))
        return result
