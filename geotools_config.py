# -*- coding: utf-8 -*-

import copy
import json
import os
from datetime import datetime


class ConfigError(Exception):
    """Raised when a JSON tool config is structurally invalid."""


PRESETS = {
    'layer_sets_default': {
        'label': 'レイヤセット作成',
        'tool': 'add_sets_layers',
        'description': 'CSVデータから施設配置検討用のレイヤセットを作成します。',
        'config': {
            'input': {
                'csv_path': '',
            },
            'layer_sets': {
                'group_selection': ['group1'],
                'selected_ward': '',
                'shape': 'circle',
                'size_mm': 2.0,
                'area_filter': {},
            },
            'output': {
                'gpkg_path': '',
                'layer_name': '',
                'add_to_project': True,
            },
        },
    },
    'study_area_builder': {
        'label': '調査エリア設定',
        'tool': 'study_area_builder',
        'description': '選択地点や地図上の座標を中心に、任意の半径で調査エリア円を作成・保存できます。行政区域と結合した調査エリアの設定にも対応しています。',
        'config': {
            'geometry': {
                'buffer_distance_m': 2000,
                'dissolve': True,
                'merge': True,
                'join_admin_polygon': True,
            },
            'output': {
                'gpkg_path': '',
                'layer_name': 'selected_polygons_red_outline',
                'crs': '',
                'add_to_project': True,
            },
        },
    },
    'merge_features_in_polygon': {
        'label': 'ポリゴン内の地物抽出',
        'tool': 'merge_features_in_polygon',
        'description': '選択ポリゴン内の表示中ポイント地物・ポリゴン地物を抽出して統合します。',
        'config': {
            'merge': {
                'mode': 'merge',
                'attribute_mode': 'union',
                'add_source_fid': True,
                'inherit_style': True,
                'output_mode': 'single',
                'name_prefix': '抽出_',
            },
            'output': {
                'gpkg_path': '',
                'layer_name': 'merged_points_in_polygon',
                'polygon_layer_name': 'merged_polygons_in_polygon',
                'layer_group_name': 'ポリゴン内の地物抽出',
                'crs': '',
                'add_to_project': True,
            },
        },
    },
}


DEFAULT_CONFIG = {
    'version': 1,
    'preset': 'merge_features_in_polygon',
    'tool': 'merge_features_in_polygon',
    'input': {},
    'output': {
        'gpkg_path': '',
        'layer_name': '',
        'crs': '',
        'add_to_project': True,
    },
    'style': {
        'inherit': True,
        'qml_path': '',
    },
    'log': {
        'save_to_file': False,
        'path': '',
    },
}


def deep_merge(base, override):
    merged = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def config_for_preset(preset_key):
    if preset_key not in PRESETS:
        raise ConfigError('Unknown preset: {0}'.format(preset_key))
    preset = PRESETS[preset_key]
    config = deep_merge(DEFAULT_CONFIG, preset.get('config', {}))
    config['preset'] = preset_key
    config['tool'] = preset['tool']
    return config


def normalize_config(config):
    if not isinstance(config, dict):
        raise ConfigError('JSON config must be an object.')

    preset_key = config.get('preset')
    if preset_key:
        normalized = deep_merge(config_for_preset(preset_key), config)
    else:
        normalized = deep_merge(DEFAULT_CONFIG, config)

    tool = normalized.get('tool')
    normalized['tool'] = tool
    valid_tools = {preset['tool'] for preset in PRESETS.values()}
    if tool not in valid_tools:
        raise ConfigError(
            'tool must be one of: {0}'.format(', '.join(sorted(valid_tools)))
        )

    output = normalized.setdefault('output', {})
    output.setdefault('gpkg_path', '')
    output.setdefault('layer_name', '')
    output.setdefault('layer_group_name', '')
    output.setdefault('crs', '')
    output.setdefault('add_to_project', True)
    return normalized


def load_config(path):
    if not path:
        raise ConfigError('Config path is empty.')
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            return normalize_config(json.load(handle))
    except json.JSONDecodeError as exc:
        raise ConfigError('Invalid JSON: {0}'.format(exc))
    except OSError as exc:
        raise ConfigError('Could not read config: {0}'.format(exc))


def save_config(path, config):
    if not path:
        raise ConfigError('Config path is empty.')
    normalized = normalize_config(config)
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(normalized, handle, ensure_ascii=False, indent=2)
        handle.write('\n')


def dumps_config(config):
    return json.dumps(normalize_config(config), ensure_ascii=False, indent=2)


class ExecutionLog:
    def __init__(self):
        self.entries = []

    def add(self, level, message):
        stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.entries.append('[{0}] {1}: {2}'.format(stamp, level.upper(), message))

    def info(self, message):
        self.add('info', message)

    def warning(self, message):
        self.add('warning', message)

    def error(self, message):
        self.add('error', message)

    def text(self):
        return '\n'.join(self.entries)

    def save_if_requested(self, config):
        log_config = config.get('log') or {}
        if not log_config.get('save_to_file'):
            return
        path = log_config.get('path')
        if not path:
            output_path = (config.get('output') or {}).get('gpkg_path')
            base_dir = os.path.dirname(output_path) if output_path else os.path.expanduser('~')
            path = os.path.join(base_dir, 'koji_geotools.log')
        with open(path, 'a', encoding='utf-8') as handle:
            handle.write(self.text())
            handle.write('\n')
