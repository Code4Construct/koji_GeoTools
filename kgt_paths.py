# -*- coding: utf-8 -*-

import os
import re

from qgis.core import QgsProject


TOOL_FOLDERS = {
    'layer_sets_default': 'レイヤセットを保存',
    'study_area_builder': '調査エリア設定',
    'merge_features_in_polygon': 'ポリゴン内の地物抽出',
}


DEFAULT_FILENAMES = {
    'layer_sets_default': 'layer_sets_config.json',
    'study_area_builder': 'study_area_builder_config.json',
    'merge_features_in_polygon': 'merge_features_in_polygon_config.json',
}


def _safe_folder_name(value):
    name = str(value or '').strip() or '未保存プロジェクト'
    return re.sub(r'[<>:"/\\|?*]+', '_', name)


def project_kgt_root(create=True):
    project = QgsProject.instance()
    project_folder = project.absolutePath()
    project_name = project.baseName()
    if not project_folder or not os.path.exists(project_folder):
        project_folder = os.path.expanduser('~')
    if not project_name:
        filename = project.fileName()
        project_name = os.path.splitext(os.path.basename(filename))[0] if filename else '未保存プロジェクト'

    root = os.path.join(project_folder, '{0}_KGTconfig'.format(_safe_folder_name(project_name)))
    if create:
        os.makedirs(root, exist_ok=True)
        for folder_name in TOOL_FOLDERS.values():
            os.makedirs(os.path.join(root, folder_name), exist_ok=True)
    return root


def tool_config_folder(preset_key, create=True):
    root = project_kgt_root(create=create)
    folder_name = TOOL_FOLDERS.get(preset_key, _safe_folder_name(preset_key))
    path = os.path.join(root, folder_name)
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def default_json_path(preset_key, filename=None, create=True):
    return os.path.join(
        tool_config_folder(preset_key, create=create),
        filename or DEFAULT_FILENAMES.get(preset_key, '{0}.json'.format(_safe_folder_name(preset_key))),
    )
