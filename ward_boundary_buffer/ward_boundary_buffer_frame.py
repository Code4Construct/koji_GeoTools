# -*- coding: utf-8 -*-

from importlib import reload
import json
import os

from qgis.PyQt.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)
from qgis.PyQt.QtGui import QColor
from qgis.core import QgsFeature, QgsGeometry, QgsProject, QgsMapLayer, QgsVectorLayer, QgsWkbTypes

from . import b01select_polygon
from . import b02add_buffer
from . import b03merge_dissolve_from_different_layers
from . import b04frame_and_save
from . import b05save_selected_points_star
from ..kgt_paths import default_json_path, tool_config_folder
from ..layer_tree_utils import move_layers_to_group
from ..ui_scaling import dpi_px


class WardBoundaryBufferSettingsCancelled(Exception):
    pass


class WardBoundaryBufferOutputSettingsDialog(QDialog):
    def __init__(self, polygon_layer_names, parent=None):
        super().__init__(parent)
        self.setWindowTitle("区境界＋円ポリゴン作成")
        self.setMinimumSize(dpi_px(760), dpi_px(390))
        self.resize(dpi_px(820), dpi_px(420))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(dpi_px(22), dpi_px(18), dpi_px(22), dpi_px(12))
        layout.setSpacing(dpi_px(12))
        header_layout = QHBoxLayout()
        header_layout.setSpacing(dpi_px(8))
        header_layout.addWidget(QLabel("この処理で使用する設定を先に指定してください。"))
        header_layout.addStretch(1)

        preset_load_button = QPushButton("プリセット呼出")
        preset_update_button = QPushButton("プリセット更新")
        config_load_button = QPushButton("設定読込")
        config_save_button = QPushButton("設定保存")
        for utility_button in (preset_load_button, preset_update_button, config_load_button, config_save_button):
            utility_button.setMinimumWidth(dpi_px(84))
        preset_load_button.clicked.connect(self.load_preset)
        preset_update_button.clicked.connect(self.update_preset)
        config_load_button.clicked.connect(self.load_config_file)
        config_save_button.clicked.connect(self.save_config_file)
        header_layout.addWidget(preset_load_button)
        header_layout.addWidget(preset_update_button)
        header_layout.addWidget(config_load_button)
        header_layout.addWidget(config_save_button)
        layout.addLayout(header_layout)

        top_form = QFormLayout()
        top_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        top_form.setHorizontalSpacing(dpi_px(12))
        top_form.setVerticalSpacing(dpi_px(16))
        layout.addLayout(top_form)

        self.output_path_edit = QLineEdit(self._default_output_path())
        output_row = QHBoxLayout()
        output_row.addWidget(self.output_path_edit, 1)
        output_button = QPushButton("参照")
        output_button.clicked.connect(self.browse_output)
        output_row.addWidget(output_button)
        top_form.addRow("出力GeoPackage", output_row)

        self.target_crs_combo = QComboBox()
        self.target_crs_combo.setEditable(True)
        self.target_crs_combo.addItems(["EPSG:6674", "EPSG:4326", "EPSG:6668"])
        top_form.addRow("保存先CRS", self.target_crs_combo)

        self.layer_group_name_edit = QLineEdit("区境界＋円ポリゴン作成")
        top_form.addRow("レイヤフォルダ名", self.layer_group_name_edit)

        layout.addSpacing(dpi_px(14))

        detail_layout = QHBoxLayout()
        detail_layout.setSpacing(dpi_px(16))
        layout.addLayout(detail_layout)

        polygon_group = QGroupBox("ポリゴン枠")
        star_group = QGroupBox("☆ポイント")
        polygon_group.setMinimumHeight(dpi_px(190))
        star_group.setMinimumHeight(dpi_px(190))
        polygon_form = QFormLayout()
        star_form = QFormLayout()
        polygon_form.setContentsMargins(dpi_px(12), dpi_px(12), dpi_px(12), dpi_px(12))
        star_form.setContentsMargins(dpi_px(12), dpi_px(12), dpi_px(12), dpi_px(12))
        polygon_form.setHorizontalSpacing(dpi_px(10))
        star_form.setHorizontalSpacing(dpi_px(10))
        polygon_form.setVerticalSpacing(dpi_px(8))
        star_form.setVerticalSpacing(dpi_px(8))
        polygon_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        star_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        polygon_group.setLayout(polygon_form)
        star_group.setLayout(star_form)
        group_style = (
            "QGroupBox {{ border: {0}px solid #c8c8c8; border-radius: {1}px; "
            "margin-top: {2}px; padding-top: {3}px; }} "
            "QGroupBox::title {{ subcontrol-origin: margin; left: {4}px; padding: 0 {5}px; color: #444; }}"
        ).format(dpi_px(1), dpi_px(4), dpi_px(10), dpi_px(8), dpi_px(10), dpi_px(4))
        polygon_group.setStyleSheet(group_style)
        star_group.setStyleSheet(group_style)
        detail_layout.addWidget(polygon_group, 1)
        detail_layout.addWidget(star_group, 1)

        self.polygon_layer_name_edit = QLineEdit("selected_polygons_red_outline")
        polygon_form.addRow("ポリゴン枠レイヤ名", self.polygon_layer_name_edit)

        self.polygon_layer_combo = QComboBox()
        self.polygon_layer_combo.addItems(polygon_layer_names)
        polygon_form.addRow("結合するポリゴンレイヤ", self.polygon_layer_combo)

        self.center_mode_combo = QComboBox()
        self.center_mode_combo.addItem("ポイント地物を選択して描く", "point_feature")
        self.center_mode_combo.addItem("地図上をクリックして座標から描く", "map_coordinate")
        polygon_form.addRow("円の中心", self.center_mode_combo)

        self.radius_spin = QDoubleSpinBox()
        self.radius_spin.setRange(1.0, 100000.0)
        self.radius_spin.setDecimals(0)
        self.radius_spin.setSingleStep(100.0)
        self.radius_spin.setSuffix(" m")
        self.radius_spin.setValue(2000.0)
        polygon_form.addRow("円の半径", self.radius_spin)

        self.outline_width_spin = QDoubleSpinBox()
        self.outline_width_spin.setRange(0.1, 20.0)
        self.outline_width_spin.setDecimals(1)
        self.outline_width_spin.setSingleStep(0.1)
        self.outline_width_spin.setSuffix(" mm")
        self.outline_width_spin.setValue(1.5)
        polygon_form.addRow("ポリゴン枠の幅", self.outline_width_spin)

        self.outline_color = "255,0,0,255"
        self.outline_color_button = QPushButton("選択")
        self.outline_color_button.clicked.connect(self.choose_outline_color)
        self.update_outline_color_button()
        polygon_form.addRow("ポリゴン枠の色", self.outline_color_button)

        self.star_layer_name_edit = QLineEdit("selected_points_red_star")
        star_form.addRow("☆ポイントレイヤ名", self.star_layer_name_edit)

        self.star_color = "255,0,0,255"
        self.star_color_button = QPushButton("選択")
        self.star_color_button.clicked.connect(lambda: self.choose_color("star_color", self.star_color_button, "☆の色を選択"))
        self.update_color_button(self.star_color_button, self.star_color)
        star_form.addRow("☆の色", self.star_color_button)

        self.star_size_spin = QDoubleSpinBox()
        self.star_size_spin.setRange(0.1, 50.0)
        self.star_size_spin.setDecimals(1)
        self.star_size_spin.setSingleStep(0.5)
        self.star_size_spin.setSuffix(" mm")
        self.star_size_spin.setValue(5.0)
        star_form.addRow("☆の大きさ", self.star_size_spin)

        self.star_outline_color = "255,0,0,255"
        self.star_outline_color_button = QPushButton("選択")
        self.star_outline_color_button.clicked.connect(lambda: self.choose_color("star_outline_color", self.star_outline_color_button, "☆の枠線色を選択"))
        self.update_color_button(self.star_outline_color_button, self.star_outline_color)
        star_form.addRow("☆の枠線色", self.star_outline_color_button)

        self.star_outline_width_spin = QDoubleSpinBox()
        self.star_outline_width_spin.setRange(0.0, 20.0)
        self.star_outline_width_spin.setDecimals(1)
        self.star_outline_width_spin.setSingleStep(0.1)
        self.star_outline_width_spin.setSuffix(" mm")
        self.star_outline_width_spin.setValue(0.3)
        star_form.addRow("☆の枠線幅", self.star_outline_width_spin)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _default_output_path(self):
        project_folder = QgsProject.instance().absolutePath()
        if project_folder and os.path.exists(project_folder):
            return os.path.join(project_folder, "ward_boundary_buffer.gpkg")
        return os.path.expanduser("~/ward_boundary_buffer.gpkg")

    def preset_path(self):
        return default_json_path("ward_boundary_buffer", "preset.json")

    def config_folder(self):
        return tool_config_folder("ward_boundary_buffer")

    def current_config(self):
        output_path = self.output_path_edit.text().strip()
        if output_path and not output_path.lower().endswith(".gpkg"):
            output_path += ".gpkg"
        return {
            "version": 1,
            "preset": "ward_boundary_buffer",
            "tool": "ward_boundary_buffer",
            "geometry": {
                "buffer_distance_m": self.radius_spin.value(),
                "merge": True,
                "dissolve": True,
                "center_mode": self.center_mode_combo.currentData() or "point_feature",
                "polygon_layer_name": self.polygon_layer_combo.currentText(),
            },
            "output": {
                "gpkg_path": output_path,
                "layer_name": self.polygon_layer_name_edit.text().strip() or "selected_polygons_red_outline",
                "crs": self.target_crs_combo.currentText().strip() or "EPSG:6674",
                "layer_group_name": self.layer_group_name_edit.text().strip() or "区境界＋円ポリゴン作成",
                "add_to_project": True,
            },
            "style": {
                "outline_color": self.outline_color,
                "outline_width_mm": self.outline_width_spin.value(),
                "star_layer_name": self.star_layer_name_edit.text().strip() or "selected_points_red_star",
                "star_color": self.star_color,
                "star_size_mm": self.star_size_spin.value(),
                "star_outline_color": self.star_outline_color,
                "star_outline_width_mm": self.star_outline_width_spin.value(),
            },
            "log": {
                "save_to_file": False,
                "path": "",
            },
        }

    def apply_config(self, config):
        geometry = config.get("geometry") or {}
        output = config.get("output") or {}
        style = config.get("style") or {}

        if output.get("gpkg_path"):
            self.output_path_edit.setText(output.get("gpkg_path"))
        if output.get("crs"):
            self._set_combo_value(self.target_crs_combo, output.get("crs"))
        if output.get("layer_name"):
            self.polygon_layer_name_edit.setText(output.get("layer_name"))
        if output.get("layer_group_name"):
            self.layer_group_name_edit.setText(output.get("layer_group_name"))

        if geometry.get("polygon_layer_name"):
            self._set_combo_value(self.polygon_layer_combo, geometry.get("polygon_layer_name"))
        if geometry.get("center_mode"):
            index = self.center_mode_combo.findData(geometry.get("center_mode"))
            if index >= 0:
                self.center_mode_combo.setCurrentIndex(index)
        if geometry.get("buffer_distance_m") is not None:
            self.radius_spin.setValue(float(geometry.get("buffer_distance_m")))

        if style.get("outline_color"):
            self.outline_color = style.get("outline_color")
            self.update_outline_color_button()
        if style.get("outline_width_mm") is not None:
            self.outline_width_spin.setValue(float(style.get("outline_width_mm")))
        if style.get("star_layer_name"):
            self.star_layer_name_edit.setText(style.get("star_layer_name"))
        if style.get("star_color"):
            self.star_color = style.get("star_color")
            self.update_color_button(self.star_color_button, self.star_color)
        if style.get("star_size_mm") is not None:
            self.star_size_spin.setValue(float(style.get("star_size_mm")))
        if style.get("star_outline_color"):
            self.star_outline_color = style.get("star_outline_color")
            self.update_color_button(self.star_outline_color_button, self.star_outline_color)
        if style.get("star_outline_width_mm") is not None:
            self.star_outline_width_spin.setValue(float(style.get("star_outline_width_mm")))

    def _set_combo_value(self, combo, value):
        value = str(value or "")
        index = combo.findText(value)
        if index >= 0:
            combo.setCurrentIndex(index)
            return
        if combo.isEditable():
            combo.setEditText(value)

    def load_preset(self):
        path = self.preset_path()
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            QMessageBox.information(
                self,
                "区境界＋バッファ作成",
                "このプロジェクトには保存済みプリセットがまだありません。\n"
                "現在の設定を保存する場合は「プリセット更新」を押してください。\n\n"
                "保存先:\n{0}".format(path),
            )
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                self.apply_config(json.load(handle))
            QMessageBox.information(self, "区境界＋バッファ作成", "プリセットを呼び出しました。")
        except Exception as exc:
            QMessageBox.warning(self, "区境界＋バッファ作成", "プリセットを読み込めませんでした: {0}".format(exc))

    def update_preset(self):
        path = self.preset_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(self.current_config(), handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            QMessageBox.information(self, "区境界＋バッファ作成", "プリセットを更新しました。")
        except Exception as exc:
            QMessageBox.warning(self, "区境界＋バッファ作成", "プリセットを更新できませんでした: {0}".format(exc))

    def load_config_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "設定を読み込み",
            self.config_folder(),
            "JSON Files (*.json);;All Files (*.*)",
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                self.apply_config(json.load(handle))
            QMessageBox.information(self, "区境界＋円ポリゴン作成", "設定を読み込みました。")
        except Exception as exc:
            QMessageBox.warning(self, "区境界＋円ポリゴン作成", "設定を読み込めませんでした: {0}".format(exc))

    def save_config_file(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "設定を保存",
            default_json_path("ward_boundary_buffer"),
            "JSON Files (*.json);;All Files (*.*)",
        )
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(self.current_config(), handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            QMessageBox.information(self, "区境界＋円ポリゴン作成", "設定を保存しました。")
        except Exception as exc:
            QMessageBox.warning(self, "区境界＋円ポリゴン作成", "設定を保存できませんでした: {0}".format(exc))

    def browse_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "出力GeoPackageを選択",
            self.output_path_edit.text().strip() or self._default_output_path(),
            "GeoPackage (*.gpkg)",
        )
        if path:
            if not path.lower().endswith(".gpkg"):
                path += ".gpkg"
            self.output_path_edit.setText(path)

    def choose_outline_color(self):
        self.choose_color("outline_color", self.outline_color_button, "ポリゴン枠の色を選択")

    def choose_color(self, property_name, button, title):
        current_color = getattr(self, property_name)
        color = QColorDialog.getColor(self._rgba_to_qcolor(current_color), self, title, QColorDialog.ShowAlphaChannel)
        if color.isValid():
            rgba = "{0},{1},{2},{3}".format(color.red(), color.green(), color.blue(), color.alpha())
            setattr(self, property_name, rgba)
            self.update_color_button(button, rgba)

    def update_outline_color_button(self):
        self.update_color_button(self.outline_color_button, self.outline_color)

    def update_color_button(self, button, color_rgba):
        color = self._rgba_to_qcolor(color_rgba)
        button.setStyleSheet(
            "QPushButton {{ background-color: rgba({0}, {1}, {2}, {3}); border: 1px solid #777; }}".format(
                color.red(),
                color.green(),
                color.blue(),
                color.alpha(),
            )
        )

    def _rgba_to_qcolor(self, value):
        parts = [part.strip() for part in str(value or "").split(",")]
        try:
            return QColor(
                int(parts[0]) if len(parts) > 0 else 255,
                int(parts[1]) if len(parts) > 1 else 0,
                int(parts[2]) if len(parts) > 2 else 0,
                int(parts[3]) if len(parts) > 3 else 255,
            )
        except ValueError:
            return QColor(255, 0, 0, 255)

    def settings(self):
        output_path = self.output_path_edit.text().strip()
        if output_path and not output_path.lower().endswith(".gpkg"):
            output_path += ".gpkg"
        return {
            "polygon_layer_name": self.polygon_layer_combo.currentText(),
            "center_mode": self.center_mode_combo.currentData() or "point_feature",
            "output_path": output_path,
            "star_layer_name": self.star_layer_name_edit.text().strip() or "selected_points_red_star",
            "polygon_output_layer_name": self.polygon_layer_name_edit.text().strip() or "selected_polygons_red_outline",
            "target_crs": self.target_crs_combo.currentText().strip() or "EPSG:6674",
            "layer_group_name": self.layer_group_name_edit.text().strip() or "区境界＋円ポリゴン作成",
            "buffer_distance_m": self.radius_spin.value(),
            "outline_width_mm": self.outline_width_spin.value(),
            "outline_color": self.outline_color,
            "star_color": self.star_color,
            "star_size_mm": self.star_size_spin.value(),
            "star_outline_color": self.star_outline_color,
            "star_outline_width_mm": self.star_outline_width_spin.value(),
        }


def create_selected_center_point_layer(iface, point, layer_name="clicked_center_point"):
    canvas_crs = iface.mapCanvas().mapSettings().destinationCrs()
    layer = QgsVectorLayer("Point?crs={0}".format(canvas_crs.authid()), layer_name, "memory")
    provider = layer.dataProvider()
    feature = QgsFeature(layer.fields())
    feature.setGeometry(QgsGeometry.fromPointXY(point))
    provider.addFeatures([feature])
    layer.updateExtents()
    QgsProject.instance().addMapLayer(layer)
    ids = [feature.id() for feature in layer.getFeatures()]
    if ids:
        layer.selectByIds([ids[0]])
    iface.setActiveLayer(layer)
    iface.mapCanvas().refresh()
    return layer


def visible_polygon_layers():
    project = QgsProject.instance()
    root = project.layerTreeRoot()
    polygon_layers = []

    for lyr in project.mapLayers().values():
        if lyr.type() == QgsMapLayer.VectorLayer:
            geom_type = QgsWkbTypes.geometryType(lyr.wkbType())
            if geom_type == QgsWkbTypes.PolygonGeometry:
                node = root.findLayer(lyr.id())
                if node is None or not node.isVisible():
                    continue
                polygon_layers.append(lyr)
    return polygon_layers


def collect_ward_boundary_buffer_output_settings(iface):
    polygon_layers = visible_polygon_layers()

    if not polygon_layers:
        raise Exception("表示中のポリゴンレイヤがありません。ポリゴンレイヤを表示ONにしてください。")

    polygon_layer_names = [lyr.name() for lyr in polygon_layers]

    default_index = 0
    if "区域EPSG_6674" in polygon_layer_names:
        default_index = polygon_layer_names.index("区域EPSG_6674")

    dialog = WardBoundaryBufferOutputSettingsDialog(polygon_layer_names, iface.mainWindow())
    dialog.polygon_layer_combo.setCurrentIndex(default_index)
    if dialog.exec_() != QDialog.Accepted:
        raise WardBoundaryBufferSettingsCancelled()
    settings = dialog.settings()
    selected_polygon_layer_name = settings["polygon_layer_name"]
    if not settings["output_path"]:
        raise Exception("出力GeoPackageを指定してください。")
    return settings


def run_ward_boundary_buffer(iface, settings=None):
    """
    選択した地物について、
    1) 地物を星印で保存
    2) 対応する区ポリゴンを選択
    3) 2kmバッファ作成
    4) 別レイヤ由来のポリゴンを統合・ディゾルブ
    5) 外枠を赤線で保存
    を実行する
    """

    reload(b01select_polygon)
    reload(b02add_buffer)
    reload(b03merge_dissolve_from_different_layers)
    reload(b04frame_and_save)
    reload(b05save_selected_points_star)

    b01 = b01select_polygon
    b02 = b02add_buffer
    b03 = b03merge_dissolve_from_different_layers
    b04 = b04frame_and_save
    b05 = b05save_selected_points_star

    if settings is None:
        settings = collect_ward_boundary_buffer_output_settings(iface)
    selected_polygon_layer_name = settings["polygon_layer_name"]

    print(f"選択したポリゴンレイヤ: {selected_polygon_layer_name}")

    _, star_layer = b05.save_selected_points_as_red_star(
        output_layer_name=settings["star_layer_name"],
        target_epsg=settings["target_crs"],
        iface_obj=iface,
        save_path=settings["output_path"],
        gpkg_layer_name=settings["star_layer_name"],
        overwrite_file=True,
        remove_source_if_memory=settings.get("center_mode") == "map_coordinate",
        star_color=settings["star_color"],
        star_size_mm=settings["star_size_mm"],
        star_outline_color=settings["star_outline_color"],
        star_outline_width_mm=settings["star_outline_width_mm"],
    )
    b01.select_polygons_from_selected_points(selected_polygon_layer_name)
    b02.create_selected_buffer(buffer_m=settings["buffer_distance_m"])
    b03.dissolve_selected_polygons()
    polygon_layer, _ = b04.export_selected_polygons_with_red_outline(
        output_layer_name=settings["polygon_output_layer_name"],
        target_epsg=settings["target_crs"],
        save_path=settings["output_path"],
        gpkg_layer_name=settings["polygon_output_layer_name"],
        overwrite_file=False,
        outline_color=settings["outline_color"],
        outline_width_mm=str(settings["outline_width_mm"]),
    )
    move_layers_to_group([star_layer, polygon_layer], settings.get("layer_group_name"))
