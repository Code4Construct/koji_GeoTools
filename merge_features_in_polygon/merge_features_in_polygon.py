# -*- coding: utf-8 -*-

import importlib
import json
import os

from qgis.PyQt.QtCore import QCoreApplication, QSettings, QTranslator, Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QAction,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)
from qgis.core import QgsMapLayer, QgsProject, QgsWkbTypes
from qgis.gui import QgsMapToolIdentify

from . import merge_visible_features_in_selected_polygon
from .resources import *
from ..kgt_paths import default_json_path, tool_config_folder
from ..ui_scaling import dpi_px


class MergeFeatureSettingsCancelled(Exception):
    pass


class MergeFeatureOutputSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('ポリゴン内の地物抽出')
        self.setMinimumSize(dpi_px(760), dpi_px(330))
        self.resize(dpi_px(820), dpi_px(360))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(dpi_px(22), dpi_px(18), dpi_px(22), dpi_px(12))
        layout.setSpacing(dpi_px(12))

        header_layout = QHBoxLayout()
        header_layout.setSpacing(dpi_px(8))
        header_layout.addWidget(QLabel('この処理で使用する設定を先に指定してください。'))
        header_layout.addStretch(1)

        preset_load_button = QPushButton('プリセット呼出')
        preset_update_button = QPushButton('プリセット更新')
        config_load_button = QPushButton('設定読込')
        config_save_button = QPushButton('設定保存')
        for button in (preset_load_button, preset_update_button, config_load_button, config_save_button):
            button.setMinimumWidth(dpi_px(84))
        preset_load_button.clicked.connect(self.load_preset)
        preset_update_button.clicked.connect(self.update_preset)
        config_load_button.clicked.connect(self.load_config_file)
        config_save_button.clicked.connect(self.save_config_file)
        header_layout.addWidget(preset_load_button)
        header_layout.addWidget(preset_update_button)
        header_layout.addWidget(config_load_button)
        header_layout.addWidget(config_save_button)
        layout.addLayout(header_layout)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setHorizontalSpacing(dpi_px(12))
        form.setVerticalSpacing(dpi_px(14))
        layout.addLayout(form)

        self.output_path_edit = QLineEdit(self._default_output_path())
        self.output_path_edit.setMinimumHeight(dpi_px(24))
        output_row = QHBoxLayout()
        output_row.setContentsMargins(0, 0, 0, 0)
        output_row.setSpacing(dpi_px(6))
        output_row.addWidget(self.output_path_edit, 1)
        output_button = QPushButton('参照')
        output_button.setMinimumHeight(dpi_px(24))
        output_button.clicked.connect(self.browse_output)
        output_row.addWidget(output_button)
        form.addRow('出力GeoPackage', output_row)

        self.output_layer_name_edit = QLineEdit('merged_points_in_polygon')
        self.output_layer_name_edit.setMinimumHeight(dpi_px(24))
        form.addRow('保存ポイントレイヤ名', self.output_layer_name_edit)

        self.output_polygon_layer_name_edit = QLineEdit('merged_polygons_in_polygon')
        self.output_polygon_layer_name_edit.setMinimumHeight(dpi_px(24))
        form.addRow('保存ポリゴンレイヤ名', self.output_polygon_layer_name_edit)

        self.layer_group_name_edit = QLineEdit('ポリゴン内の地物抽出')
        self.layer_group_name_edit.setMinimumHeight(dpi_px(24))
        form.addRow('レイヤフォルダ名', self.layer_group_name_edit)

        self.output_crs_combo = QComboBox()
        self.output_crs_combo.setEditable(True)
        self.output_crs_combo.setMinimumHeight(dpi_px(24))
        self.output_crs_combo.addItem('対象ポリゴンCRSを使用', '')
        self.output_crs_combo.addItems(['EPSG:6674', 'EPSG:4326', 'EPSG:3857', 'EPSG:6668'])
        form.addRow('保存CRS', self.output_crs_combo)

        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.setSpacing(dpi_px(10))
        self.output_mode_combo = QComboBox()
        self.output_mode_combo.setMinimumHeight(dpi_px(24))
        self.output_mode_combo.addItem('ポイント・ポリゴンをそれぞれ１レイヤとして保存', 'single')
        self.output_mode_combo.addItem('既存のレイヤグループ、レイヤ分けとスタイルを継承保存', 'split_by_source')
        mode_row.addWidget(self.output_mode_combo, 1)
        mode_row.addWidget(QLabel('接頭語'))
        self.name_prefix_edit = QLineEdit('抽出_')
        self.name_prefix_edit.setMinimumHeight(dpi_px(24))
        mode_row.addWidget(self.name_prefix_edit)
        form.addRow('保存方式', mode_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        for button in buttons.buttons():
            button.setMinimumHeight(dpi_px(24))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _default_output_path(self):
        project_folder = QgsProject.instance().absolutePath()
        if project_folder and os.path.exists(project_folder):
            return os.path.join(project_folder, 'merged_points_in_polygon.gpkg')
        return os.path.expanduser('~/merged_points_in_polygon.gpkg')

    def preset_path(self):
        return default_json_path('merge_features_in_polygon', 'preset.json')

    def config_folder(self):
        return tool_config_folder('merge_features_in_polygon')

    def current_config(self):
        output_path = self.output_path_edit.text().strip()
        if output_path and not output_path.lower().endswith('.gpkg'):
            output_path += '.gpkg'
        return {
            'version': 1,
            'preset': 'merge_features_in_polygon',
            'tool': 'merge_features_in_polygon',
            'merge': {
                'mode': 'merge',
                'attribute_mode': 'union',
                'add_source_fid': True,
                'inherit_style': True,
                'output_mode': self.output_mode_combo.currentData() or 'single',
                'name_prefix': self.name_prefix_edit.text().strip(),
            },
            'output': {
                'gpkg_path': output_path,
                'layer_name': self.output_layer_name_edit.text().strip() or 'merged_points_in_polygon',
                'polygon_layer_name': self.output_polygon_layer_name_edit.text().strip() or 'merged_polygons_in_polygon',
                'layer_group_name': self.layer_group_name_edit.text().strip() or 'ポリゴン内の地物抽出',
                'crs': self.output_crs_combo.currentData() if self.output_crs_combo.currentData() is not None else self.output_crs_combo.currentText().strip(),
                'add_to_project': True,
            },
            'log': {
                'save_to_file': False,
                'path': '',
            },
        }

    def apply_config(self, config):
        output = config.get('output') or {}
        merge = config.get('merge') or {}
        if output.get('gpkg_path'):
            self.output_path_edit.setText(output.get('gpkg_path'))
        if output.get('layer_name'):
            self.output_layer_name_edit.setText(output.get('layer_name'))
        if output.get('polygon_layer_name'):
            self.output_polygon_layer_name_edit.setText(output.get('polygon_layer_name'))
        if output.get('layer_group_name'):
            self.layer_group_name_edit.setText(output.get('layer_group_name'))
        if output.get('crs'):
            self._set_combo_value(self.output_crs_combo, output.get('crs'))
        if merge.get('output_mode'):
            index = self.output_mode_combo.findData(merge.get('output_mode'))
            if index >= 0:
                self.output_mode_combo.setCurrentIndex(index)
        if merge.get('name_prefix') is not None:
            self.name_prefix_edit.setText(str(merge.get('name_prefix') or ''))

    def settings(self):
        config = self.current_config()
        output = config.get('output') or {}
        merge = config.get('merge') or {}
        return {
            'output_path': output.get('gpkg_path') or '',
            'output_layer_name': output.get('layer_name') or 'merged_points_in_polygon',
            'output_polygon_layer_name': output.get('polygon_layer_name') or 'merged_polygons_in_polygon',
            'layer_group_name': output.get('layer_group_name') or 'ポリゴン内の地物抽出',
            'output_crs': output.get('crs') or '',
            'add_source_fid': merge.get('add_source_fid', True),
            'inherit_style': merge.get('inherit_style', True),
            'output_mode': merge.get('output_mode') or 'single',
            'name_prefix': merge.get('name_prefix') or '',
        }

    def _set_combo_value(self, combo, value):
        value = str(value or '')
        index = combo.findText(value)
        if index < 0:
            index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)
        elif combo.isEditable():
            combo.setEditText(value)

    def load_preset(self):
        path = self.preset_path()
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            QMessageBox.information(
                self,
                'ポリゴン内の地物抽出',
                'このプロジェクトには保存済みプリセットがまだありません。\n'
                '現在の設定を保存する場合は「プリセット更新」を押してください。\n\n'
                '保存先:\n{0}'.format(path),
            )
            return
        try:
            with open(path, 'r', encoding='utf-8') as handle:
                self.apply_config(json.load(handle))
            QMessageBox.information(self, 'ポリゴン内の地物抽出', 'プリセットを呼び出しました。')
        except Exception as exc:
            QMessageBox.warning(self, 'ポリゴン内の地物抽出', 'プリセットを読み込めませんでした: {0}'.format(exc))

    def update_preset(self):
        path = self.preset_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as handle:
                json.dump(self.current_config(), handle, ensure_ascii=False, indent=2)
                handle.write('\n')
            QMessageBox.information(self, 'ポリゴン内の地物抽出', 'プリセットを更新しました。')
        except Exception as exc:
            QMessageBox.warning(self, 'ポリゴン内の地物抽出', 'プリセットを更新できませんでした: {0}'.format(exc))

    def load_config_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            '設定を読み込み',
            self.config_folder(),
            'JSON Files (*.json);;All Files (*.*)',
        )
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as handle:
                self.apply_config(json.load(handle))
            QMessageBox.information(self, 'ポリゴン内の地物抽出', '設定を読み込みました。')
        except Exception as exc:
            QMessageBox.warning(self, 'ポリゴン内の地物抽出', '設定を読み込めませんでした: {0}'.format(exc))

    def save_config_file(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            '設定を保存',
            default_json_path('merge_features_in_polygon'),
            'JSON Files (*.json);;All Files (*.*)',
        )
        if not path:
            return
        if not path.lower().endswith('.json'):
            path += '.json'
        try:
            with open(path, 'w', encoding='utf-8') as handle:
                json.dump(self.current_config(), handle, ensure_ascii=False, indent=2)
                handle.write('\n')
            QMessageBox.information(self, 'ポリゴン内の地物抽出', '設定を保存しました。')
        except Exception as exc:
            QMessageBox.warning(self, 'ポリゴン内の地物抽出', '設定を保存できませんでした: {0}'.format(exc))

    def browse_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            '出力GeoPackageを選択',
            self.output_path_edit.text().strip() or self._default_output_path(),
            'GeoPackage (*.gpkg)',
        )
        if path:
            if not path.lower().endswith('.gpkg'):
                path += '.gpkg'
            self.output_path_edit.setText(path)


def collect_merge_feature_output_settings(iface):
    dialog = MergeFeatureOutputSettingsDialog(iface.mainWindow())
    if dialog.exec_() != QDialog.Accepted:
        raise MergeFeatureSettingsCancelled()
    settings = dialog.settings()
    if not settings['output_path']:
        raise Exception('出力GeoPackageを指定してください。')
    return settings


class PolygonPickAndRunMapTool(QgsMapToolIdentify):
    def __init__(self, iface, run_callback, previous_tool=None):
        super().__init__(iface.mapCanvas())
        self.iface = iface
        self.run_callback = run_callback
        self.previous_tool = previous_tool
        self.is_koji_merge_pick_tool = True
        self.cancelled = False
        self.setCursor(Qt.CrossCursor)

    def canvasReleaseEvent(self, event):
        if self.cancelled:
            return
        results = self.identify(event.x(), event.y(), self.TopDownAll, self.VectorLayer)
        for result in results:
            layer = result.mLayer
            if not self._is_polygon_layer(layer):
                continue
            feature = result.mFeature
            self._select_polygon(layer, feature.id())
            self._restore_previous_tool()
            self._run_callback()
            return

        QMessageBox.information(
            self.iface.mainWindow(),
            'ポリゴン内の地物抽出',
            'クリックした位置にポリゴン地物が見つかりませんでした。ポリゴン地物をクリックしてください。',
        )

    def _is_polygon_layer(self, layer):
        if layer is None or layer.type() != QgsMapLayer.VectorLayer:
            return False
        return QgsWkbTypes.geometryType(layer.wkbType()) == QgsWkbTypes.PolygonGeometry

    def _select_polygon(self, target_layer, feature_id):
        for layer in QgsProject.instance().mapLayers().values():
            if self._is_polygon_layer(layer):
                layer.removeSelection()
        self.iface.setActiveLayer(target_layer)
        target_layer.selectByIds([feature_id])
        self.iface.mapCanvas().refresh()

    def _restore_previous_tool(self):
        if self.previous_tool is not None:
            self.canvas().setMapTool(self.previous_tool)
        elif hasattr(self.canvas(), 'unsetMapTool'):
            self.canvas().unsetMapTool(self)

    def cancel(self):
        self.cancelled = True
        self._restore_previous_tool()

    def _run_callback(self):
        try:
            self.run_callback()
        except Exception as exc:
            QMessageBox.critical(
                self.iface.mainWindow(),
                'ポリゴン内の地物抽出',
                str(exc),
            )


class MergeFeaturesInPolygon:
    """QGIS plugin wrapper for merging visible features in a polygon."""

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.pick_tool = None
        locale = QSettings().value('locale/userLocale')[0:2]
        locale_path = os.path.join(
            self.plugin_dir,
            'i18n',
            'MergeFeaturesInPolygon_{}.qm'.format(locale),
        )

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)
            QCoreApplication.installTranslator(self.translator)

        self.actions = []
        self.menu = self.tr(u'&ポリゴン内の地物抽出')

    def tr(self, message):
        return QCoreApplication.translate('MergeFeaturesInPolygon', message)

    def add_action(
        self,
        icon_path,
        text,
        callback,
        enabled_flag=True,
        add_to_menu=True,
        add_to_toolbar=True,
        status_tip=None,
        whats_this=None,
        parent=None,
    ):
        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)
        if whats_this is not None:
            action.setWhatsThis(whats_this)
        if add_to_toolbar:
            self.iface.addToolBarIcon(action)
        if add_to_menu:
            self.iface.addPluginToMenu(self.menu, action)

        self.actions.append(action)
        return action

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, 'icon.png')
        self.add_action(
            icon_path,
            text=self.tr(u'ポリゴン内の地物抽出'),
            callback=self.run,
            parent=self.iface.mainWindow(),
        )

    def unload(self):
        for action in self.actions:
            self.iface.removePluginMenu(
                self.tr(u'&ポリゴン内の地物抽出'),
                action,
            )
            self.iface.removeToolBarIcon(action)

    def show_plugin_description(self):
        select_image_path = os.path.join(
            self.plugin_dir,
            'images',
            'select.png',
        ).replace(os.sep, '/')

        QMessageBox.information(
            self.iface.mainWindow(),
            self.tr(u'ポリゴン内の地物抽出'),
            self.tr(
                u'<p>このプラグインは、選択したポリゴン内にある表示中のポイント地物とポリゴン地物を抽出し、'
                u'GeoPackageレイヤとして保存します。</p>'
                u'<p><b>使い方:</b></p>'
                u'<p>1. ポリゴンレイヤで対象ポリゴンを選択します。<br>'
                u'<img src="{select_image_path}" width="50" height="37"></p>'
                u'<p>2. 抽出対象にしたいポイントレイヤまたはポリゴンレイヤを表示状態にします。</p>'
                u'<p>3. OKを押すと保存先を選び、抽出結果をQGISに追加します。</p>'
            ).format(select_image_path=select_image_path),
        )

    def run(self):
        self.cancel_pick_tool()
        try:
            settings = collect_merge_feature_output_settings(self.iface)
        except MergeFeatureSettingsCancelled:
            return

        canvas = self.iface.mapCanvas()
        previous_tool = canvas.mapTool()
        self.pick_tool = PolygonPickAndRunMapTool(
            self.iface,
            lambda: self.run_with_settings(settings),
            previous_tool,
        )
        canvas.setMapTool(self.pick_tool)
        self.iface.messageBar().pushInfo(
            'ポリゴン内の地物抽出',
            '抽出範囲にするポリゴン地物を地図上でクリックしてください。',
        )

    def cancel_pick_tool(self):
        canvas = self.iface.mapCanvas()
        current_tool = canvas.mapTool()
        if getattr(current_tool, 'is_koji_merge_pick_tool', False):
            try:
                current_tool.cancel()
            except Exception:
                pass
        if self.pick_tool is not None:
            try:
                self.pick_tool.cancel()
            except Exception:
                pass
            self.pick_tool = None

    def run_with_settings(self, settings):
        self.pick_tool = None
        importlib.reload(merge_visible_features_in_selected_polygon)
        merge_visible_features_in_selected_polygon.run_merge_visible_features_in_selected_polygon(
            self.iface,
            output_path=settings['output_path'],
            output_layer_name=settings['output_layer_name'],
            output_polygon_layer_name=settings['output_polygon_layer_name'],
            output_crs=settings['output_crs'],
            add_source_fid=settings['add_source_fid'],
            inherit_style=settings['inherit_style'],
            layer_group_name=settings['layer_group_name'],
            output_mode=settings['output_mode'],
            name_prefix=settings['name_prefix'],
        )
