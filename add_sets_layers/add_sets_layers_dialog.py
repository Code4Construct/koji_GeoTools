# -*- coding: utf-8 -*-

import csv
import json
import os

from qgis.PyQt.QtCore import QEvent, QTimer, Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..kgt_paths import default_json_path, tool_config_folder
from ..ui_scaling import dpi_px


def _table_text(table, row, column):
    item = table.item(row, column)
    return item.text().strip() if item is not None else ''


def _rgba_to_qcolor(value):
    parts = [part.strip() for part in str(value or '').split(',')]
    try:
        red = int(parts[0]) if len(parts) > 0 else 0
        green = int(parts[1]) if len(parts) > 1 else 112
        blue = int(parts[2]) if len(parts) > 2 else 255
        alpha = int(parts[3]) if len(parts) > 3 else 255
        return QColor(red, green, blue, alpha)
    except ValueError:
        return QColor(0, 112, 255, 255)


def _qcolor_to_rgba(color):
    return '{0},{1},{2},{3}'.format(color.red(), color.green(), color.blue(), color.alpha())


def _quote_field(field_name):
    return '"{0}"'.format(str(field_name).replace('"', '""'))


def _color_button_style(color):
    rgba = _rgba_to_qcolor(color)
    return (
        'QPushButton {{ background-color: rgba({0}, {1}, {2}, {3}); '
        'border: {4}px solid #777; padding-left: {5}px; padding-right: {5}px; }}'
    ).format(rgba.red(), rgba.green(), rgba.blue(), rgba.alpha(), dpi_px(1), dpi_px(2))


def _compact_spinbox_style():
    return (
        'QSpinBox::up-button, QSpinBox::down-button, '
        'QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: {0}px; }}'
    ).format(dpi_px(10))


class LabelExpressionDialog(QDialog):
    def __init__(self, expression='', parent=None):
        super().__init__(parent)
        self.setWindowTitle('ラベル詳細設定')
        self.setMinimumSize(dpi_px(520), dpi_px(110))
        self.resize(dpi_px(720), dpi_px(120))

        layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        self.expression_edit = QLineEdit(expression or '')
        form_layout.addRow('value', self.expression_edit)
        layout.addLayout(form_layout)

        button_row = QHBoxLayout()
        clear_button = QPushButton('Clear')
        clear_button.clicked.connect(self.expression_edit.clear)
        button_row.addWidget(clear_button)
        button_row.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        button_row.addWidget(buttons)
        layout.addLayout(button_row)

    def expression(self):
        return self.expression_edit.text().strip()


class LayerConditionDialog(QDialog):
    FILTER_KINDS = [
        ('文字列', 'text'),
        ('数量制限', 'number'),
        ('現西暦-数値', 'year_minus_number'),
    ]
    CONDITIONS_BY_KIND = {
        'text': [
            ('空白', 'empty'),
            ('空白ではない', 'not_empty'),
            ('一致する', 'equals'),
            ('一致しない', 'not_equals'),
            ('含む', 'contains'),
            ('含まない', 'not_contains'),
            ('で始まる', 'starts_with'),
            ('で終わる', 'ends_with'),
        ],
        'number': [
            ('空白', 'empty'),
            ('空白ではない', 'not_empty'),
            ('=', 'equals'),
            ('!=', 'not_equals'),
            ('以上', 'greater_equal'),
            ('より大きい', 'greater_than'),
            ('以下', 'less_equal'),
            ('より小さい', 'less_than'),
            ('範囲内（以上未満）', 'between'),
        ],
        'year_minus_number': [
            ('空白', 'empty'),
            ('空白ではない', 'not_empty'),
            ('=', 'equals'),
            ('!=', 'not_equals'),
            ('以上', 'greater_equal'),
            ('より大きい', 'greater_than'),
            ('以下', 'less_equal'),
            ('より小さい', 'less_than'),
            ('範囲内（以上未満）', 'between'),
        ],
    }

    def __init__(self, fields, rules=None, action='include', match_mode='all', parent=None):
        super().__init__(parent)
        self.fields = list(fields or [])
        self.setWindowTitle('レイヤ条件設定')
        self.setMinimumSize(dpi_px(780), dpi_px(460))
        self.resize(dpi_px(980), dpi_px(560))

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(QLabel('このレイヤに含める行の条件を設定します。対象列と条件を選んでください。'))

        body_layout = QHBoxLayout()
        main_layout.addLayout(body_layout, 1)

        left_layout = QVBoxLayout()
        body_layout.addLayout(left_layout, 0)
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText('列名で絞り込み')
        self.filter_edit.textChanged.connect(self.apply_filter)
        left_layout.addWidget(self.filter_edit)

        self.field_table = QTableWidget(0, 1)
        self.field_table.setHorizontalHeaderLabels(['列名'])
        self.field_table.horizontalHeader().setStretchLastSection(True)
        self.field_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.field_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.field_table.itemDoubleClicked.connect(self.add_selected_field_rule)
        left_layout.addWidget(self.field_table, 1)

        right_layout = QVBoxLayout()
        body_layout.addLayout(right_layout, 1)

        condition_group = QGroupBox('抽出条件')
        right_layout.addWidget(condition_group)
        condition_layout = QVBoxLayout(condition_group)

        form_layout = QFormLayout()
        self.action_combo = QComboBox()
        self.action_combo.addItem('条件に合う行だけを残す', 'include')
        self.action_combo.addItem('条件に合う行を除外する', 'exclude')
        self.action_combo.setCurrentIndex(max(0, self.action_combo.findData(action)))
        form_layout.addRow('動作', self.action_combo)

        self.match_mode_combo = QComboBox()
        self.match_mode_combo.addItem('すべての列が条件に合う', 'all')
        self.match_mode_combo.addItem('いずれかの列が条件に合う', 'any')
        self.match_mode_combo.setCurrentIndex(max(0, self.match_mode_combo.findData(match_mode)))
        form_layout.addRow('判定', self.match_mode_combo)
        condition_layout.addLayout(form_layout)

        self.rules_table = QTableWidget(0, 5)
        self.rules_table.setHorizontalHeaderLabels(['列名', '種類', '条件', '値1', '値2'])
        self.rules_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.rules_table.setColumnWidth(1, dpi_px(120))
        self.rules_table.setColumnWidth(2, dpi_px(150))
        self.rules_table.setColumnWidth(3, dpi_px(160))
        self.rules_table.setColumnWidth(4, dpi_px(160))
        condition_layout.addWidget(self.rules_table, 1)

        button_row = QHBoxLayout()
        add_button = QPushButton('選択列を追加')
        remove_button = QPushButton('条件を削除')
        add_button.clicked.connect(self.add_selected_field_rule)
        remove_button.clicked.connect(self.remove_selected_rule)
        button_row.addWidget(add_button)
        button_row.addWidget(remove_button)
        button_row.addStretch(1)
        condition_layout.addLayout(button_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

        self.populate_fields()
        for rule in rules or []:
            self.add_rule(rule)

    def populate_fields(self):
        self.field_table.setRowCount(0)
        for field in self.fields:
            row = self.field_table.rowCount()
            self.field_table.insertRow(row)
            self.field_table.setItem(row, 0, QTableWidgetItem(field))

    def apply_filter(self, text):
        needle = text.strip().lower()
        for row in range(self.field_table.rowCount()):
            value = _table_text(self.field_table, row, 0).lower()
            self.field_table.setRowHidden(row, bool(needle and needle not in value))

    def selected_field(self):
        row = self.field_table.currentRow()
        if row < 0:
            return None
        return _table_text(self.field_table, row, 0)

    def add_selected_field_rule(self):
        field = self.selected_field()
        if not field:
            return
        self.add_rule({'field': field, 'filter_kind': 'text', 'condition': 'contains'})

    def add_rule(self, rule):
        row = self.rules_table.rowCount()
        self.rules_table.insertRow(row)
        self.rules_table.setItem(row, 0, QTableWidgetItem(rule.get('field') or ''))

        kind_combo = QComboBox()
        for label, data in self.FILTER_KINDS:
            kind_combo.addItem(label, data)
        kind_combo.setCurrentIndex(max(0, kind_combo.findData(rule.get('filter_kind') or 'text')))
        kind_combo.currentIndexChanged.connect(lambda index, r=row: self.refresh_condition_combo(r))
        self.rules_table.setCellWidget(row, 1, kind_combo)

        condition_combo = QComboBox()
        self.rules_table.setCellWidget(row, 2, condition_combo)
        self.refresh_condition_combo(row, rule.get('condition') or 'contains')

        self.rules_table.setItem(row, 3, QTableWidgetItem(str(rule.get('value') or '')))
        self.rules_table.setItem(row, 4, QTableWidgetItem(str(rule.get('value2') or '')))

    def refresh_condition_combo(self, row, current=None):
        kind_combo = self.rules_table.cellWidget(row, 1)
        condition_combo = self.rules_table.cellWidget(row, 2)
        if condition_combo is None:
            return
        kind = kind_combo.currentData() if kind_combo else 'text'
        old_value = current or condition_combo.currentData()
        condition_combo.blockSignals(True)
        condition_combo.clear()
        for label, data in self.CONDITIONS_BY_KIND.get(kind, []):
            condition_combo.addItem(label, data)
        index = condition_combo.findData(old_value)
        condition_combo.setCurrentIndex(index if index >= 0 else 0)
        condition_combo.blockSignals(False)

    def remove_selected_rule(self):
        row = self.rules_table.currentRow()
        if row >= 0:
            self.rules_table.removeRow(row)

    def config(self):
        rules = []
        for row in range(self.rules_table.rowCount()):
            kind_combo = self.rules_table.cellWidget(row, 1)
            condition_combo = self.rules_table.cellWidget(row, 2)
            field = _table_text(self.rules_table, row, 0)
            if not field:
                continue
            rules.append({
                'field': field,
                'filter_kind': kind_combo.currentData() if kind_combo else 'text',
                'condition': condition_combo.currentData() if condition_combo else 'contains',
                'value': _table_text(self.rules_table, row, 3),
                'value2': _table_text(self.rules_table, row, 4),
            })
        return {
            'action': self.action_combo.currentData(),
            'match_mode': self.match_mode_combo.currentData(),
            'rules': rules,
        }


class Add_Sets_LayersDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.fields = []
        self.condition_configs = {}
        self.setWindowTitle('レイヤセット作成')
        self.setMinimumSize(dpi_px(960), dpi_px(520))
        self.resize(dpi_px(1280), dpi_px(620))
        self._adjusting_layer_table_columns = False
        self._build_ui()
        self.add_layer_definition()
        self.schedule_layer_table_column_adjustment()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.addWidget(QLabel('CSVから追加するレイヤを1つずつ設定します。各レイヤの条件は「条件設定」から編集できます。'))

        io_group = QGroupBox('入出力')
        main_layout.addWidget(io_group)
        io_layout = QGridLayout(io_group)

        self.csv_path_edit = QLineEdit()
        csv_button = QPushButton('参照')
        csv_button.clicked.connect(self.browse_csv)
        io_layout.addWidget(QLabel('入力CSV'), 0, 0)
        io_layout.addWidget(self.csv_path_edit, 0, 1)
        io_layout.addWidget(csv_button, 0, 2)

        self.output_path_edit = QLineEdit()
        output_button = QPushButton('参照')
        output_button.clicked.connect(self.browse_output)
        self.output_crs_combo = QComboBox()
        self.output_crs_combo.setEditable(True)
        self.output_crs_combo.setMinimumWidth(dpi_px(130))
        io_layout.addWidget(QLabel('出力GeoPackage'), 2, 0)
        output_layout = QHBoxLayout()
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.setSpacing(dpi_px(6))
        output_layout.addWidget(self.output_path_edit, 1)
        output_layout.addWidget(output_button)
        output_layout.addWidget(QLabel('出力CRS'))
        output_layout.addWidget(self.output_crs_combo)
        output_widget = QWidget()
        output_widget.setLayout(output_layout)
        io_layout.addWidget(output_widget, 2, 1, 1, 2)

        self.x_field_combo = QComboBox()
        self.x_field_combo.setEditable(True)
        self.y_field_combo = QComboBox()
        self.y_field_combo.setEditable(True)
        self.crs_combo = QComboBox()
        self.crs_combo.setEditable(True)
        self._populate_crs_choices('EPSG:4326')
        self._populate_crs_choices('EPSG:4326', self.output_crs_combo)
        self._set_combo_value(self.x_field_combo, '世界_10進_X')
        self._set_combo_value(self.y_field_combo, '世界_10進_Y')
        coord_layout = QHBoxLayout()
        coord_layout.setContentsMargins(dpi_px(32), 0, 0, 0)
        coord_layout.setSpacing(dpi_px(6))
        coord_layout.addWidget(QLabel('CSV座標'))
        coord_layout.addWidget(QLabel('X列'))
        coord_layout.addWidget(self.x_field_combo, 1)
        coord_layout.addWidget(QLabel('Y列'))
        coord_layout.addWidget(self.y_field_combo, 1)
        coord_layout.addWidget(QLabel('CRS'))
        coord_layout.addWidget(self.crs_combo, 1)
        coord_widget = QWidget()
        coord_widget.setLayout(coord_layout)
        io_layout.addWidget(coord_widget, 1, 0, 1, 3)
        io_layout.setColumnStretch(1, 1)

        layer_group = QGroupBox('レイヤ設定')
        main_layout.addWidget(layer_group, 1)
        layer_layout = QVBoxLayout(layer_group)

        self.layers_table = QTableWidget(0, 13)
        self.layers_table.setHorizontalHeaderLabels([
            'ON', '階層', 'レイヤ名', 'ラベルのデータ設定', '詳細設定',
            '描画条件', '文字サイズ', '文字色', 'シンボル', 'シンボルサイズ', 'シンボル色', '背景透過', '背景色'
        ])
        self.layers_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._style_layer_table_headers()
        self.layers_table.cellClicked.connect(self.handle_layer_cell_clicked)
        self.layers_table.cellDoubleClicked.connect(self.handle_layer_cell_clicked)
        self.layers_table.itemChanged.connect(self.handle_layer_item_changed)
        layer_layout.addWidget(self.layers_table, 1)

        row_buttons = QHBoxLayout()
        add_button = QPushButton('レイヤ追加')
        add_group_button = QPushButton('レイヤグループ追加')
        duplicate_button = QPushButton('複製')
        remove_button = QPushButton('削除')
        up_button = QPushButton('上')
        down_button = QPushButton('下')
        add_button.clicked.connect(self.add_layer_definition)
        add_group_button.clicked.connect(self.add_group_definition)
        duplicate_button.clicked.connect(self.duplicate_layer_definition)
        remove_button.clicked.connect(self.remove_layer_definition)
        up_button.clicked.connect(self.move_selected_row_up)
        down_button.clicked.connect(self.move_selected_row_down)
        row_buttons.addWidget(add_button)
        row_buttons.addWidget(add_group_button)
        row_buttons.addWidget(duplicate_button)
        row_buttons.addWidget(remove_button)
        row_buttons.addWidget(up_button)
        row_buttons.addWidget(down_button)
        row_buttons.addStretch(1)
        preset_load_button = QPushButton('プリセット呼出')
        preset_update_button = QPushButton('プリセット更新')
        config_load_button = QPushButton('設定読込')
        config_save_button = QPushButton('設定保存')
        preset_load_button.clicked.connect(self.load_preset)
        preset_update_button.clicked.connect(self.update_preset)
        config_load_button.clicked.connect(self.load_config_file)
        config_save_button.clicked.connect(self.save_config_file)
        row_buttons.addWidget(preset_load_button)
        row_buttons.addWidget(preset_update_button)
        row_buttons.addWidget(config_load_button)
        row_buttons.addWidget(config_save_button)
        layer_layout.addLayout(row_buttons)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.run_button = buttons.button(QDialogButtonBox.Ok)
        if self.run_button is not None:
            self.run_button.setMinimumHeight(dpi_px(34))
            self.run_button.setMinimumWidth(dpi_px(360))
            self.run_button.setStyleSheet(
                'font-weight: bold; padding-left: {0}px; padding-right: {0}px;'.format(dpi_px(14))
            )
        cancel_button = buttons.button(QDialogButtonBox.Cancel)
        if cancel_button is not None:
            cancel_button.setText('Cancel')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)
        self.update_run_button_text()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'layers_table'):
            self.schedule_layer_table_column_adjustment()

    def showEvent(self, event):
        super().showEvent(event)
        if hasattr(self, 'layers_table'):
            self.schedule_layer_table_column_adjustment()

    def schedule_layer_table_column_adjustment(self):
        QTimer.singleShot(0, self.adjust_layer_table_columns)

    def schedule_run_button_text_update(self):
        QTimer.singleShot(0, self.update_run_button_text)

    def enabled_layer_counts(self):
        group_count = 0
        layer_count = 0
        for row in range(self.layers_table.rowCount()):
            enabled_item = self.layers_table.item(row, 0)
            enabled = enabled_item.checkState() == Qt.Checked if enabled_item is not None else True
            if not enabled:
                continue
            if self._row_type(row) == 'group':
                group_count += 1
            else:
                layer_count += 1
        return group_count, layer_count

    def update_run_button_text(self):
        if not hasattr(self, 'run_button') or self.run_button is None:
            return
        group_count, layer_count = self.enabled_layer_counts()
        self.run_button.setText(
            '{0}個のレイヤグループと{1}個のレイヤを描画して出力GeoPackageに保存する'.format(
                group_count,
                layer_count,
            )
        )

    def adjust_layer_table_columns(self):
        if self._adjusting_layer_table_columns or not hasattr(self, 'layers_table'):
            return
        self._adjusting_layer_table_columns = True
        try:
            header = self.layers_table.horizontalHeader()
            font_metrics = header.fontMetrics()
            base_widths = {
                0: dpi_px(48),
                1: dpi_px(58),
                2: dpi_px(230),
                3: dpi_px(150),
                4: dpi_px(68),
                5: dpi_px(74),
                6: dpi_px(84),
                7: dpi_px(68),
                8: dpi_px(64),
                9: dpi_px(100),
                10: dpi_px(78),
                11: dpi_px(82),
                12: dpi_px(68),
            }
            widths = []
            for column in range(self.layers_table.columnCount()):
                item = self.layers_table.horizontalHeaderItem(column)
                header_text = item.text() if item is not None else ''
                header_width = font_metrics.horizontalAdvance(header_text) + dpi_px(18)
                widths.append(max(base_widths.get(column, dpi_px(64)), header_width))

            available = self.layers_table.viewport().width()
            if available <= 0:
                available = sum(widths)
            total = sum(widths)
            if total > available:
                extra_window_width = total - available + dpi_px(42)
                self.resize(self.width() + extra_window_width, self.height())
                available = self.layers_table.viewport().width()

            extra = max(0, available - sum(widths) - dpi_px(4))
            if extra:
                widths[2] += int(extra * 0.55)
                widths[3] += extra - int(extra * 0.55)

            for column, width in enumerate(widths):
                self.layers_table.setColumnWidth(column, width)
        finally:
            self._adjusting_layer_table_columns = False

    def _style_layer_table_headers(self):
        header = self.layers_table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignCenter)
        base_color = QColor(232, 232, 232)
        white = QColor(255, 255, 255)
        groups = [
            {'columns': (0,), 'background': white, 'tooltip': '表示設定'},
            {'columns': (1,), 'background': base_color, 'tooltip': '階層設定'},
            {'columns': (2,), 'background': white, 'tooltip': 'レイヤ設定'},
            {'columns': (3, 4), 'background': base_color, 'tooltip': 'ラベルデータ設定'},
            {'columns': (5,), 'background': white, 'tooltip': '描画条件'},
            {'columns': (6, 7), 'background': base_color, 'tooltip': 'ラベル文字設定'},
            {'columns': (8, 9, 10), 'background': white, 'tooltip': 'シンボル設定'},
            {'columns': (11, 12), 'background': base_color, 'tooltip': 'ラベル背景設定'},
        ]
        for group in groups:
            for column in group['columns']:
                item = self.layers_table.horizontalHeaderItem(column)
                if item is None:
                    continue
                item.setBackground(group['background'])
                item.setForeground(QColor(30, 30, 30))
                item.setTextAlignment(Qt.AlignCenter)
                item.setToolTip(group['tooltip'])

    def browse_csv(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            'CSVを選択',
            os.path.expanduser('~'),
            'CSV Files (*.csv);;All Files (*.*)',
        )
        if path:
            self.csv_path_edit.setText(path)
            self.load_fields_from_csv(path)

    def browse_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            'GeoPackage出力先',
            os.path.expanduser('~/layer_sets.gpkg'),
            'GeoPackage (*.gpkg)',
        )
        if path:
            if not path.lower().endswith('.gpkg'):
                path += '.gpkg'
            self.output_path_edit.setText(path)

    def _set_combo_value(self, combo, value):
        value = value or ''
        index = combo.findText(value)
        if index < 0 and value:
            combo.addItem(value)
            index = combo.findText(value)
        combo.setCurrentIndex(index if index >= 0 else -1)
        if combo.isEditable():
            combo.setEditText(value)

    def _populate_crs_choices(self, current='EPSG:4326', combo=None):
        if combo is None:
            combo = self.crs_combo
        choices = [
            'EPSG:4326',
            'EPSG:3857',
            'EPSG:6668',
            'EPSG:6674',
            'EPSG:6675',
            'EPSG:6676',
            'EPSG:6677',
        ]
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(choices)
        combo.blockSignals(False)
        self._set_combo_value(combo, current or 'EPSG:4326')

    def _populate_field_choices(self, selected_x=None, selected_y=None):
        current_x = selected_x or self.x_field()
        current_y = selected_y or self.y_field()
        for combo in (self.x_field_combo, self.y_field_combo):
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(self.fields)
            combo.blockSignals(False)
        self._set_combo_value(self.x_field_combo, current_x or '世界_10進_X')
        self._set_combo_value(self.y_field_combo, current_y or '世界_10進_Y')
        self.refresh_label_field_choices()

    def _populate_label_combo(self, combo, current=None):
        current = current or ''
        combo.blockSignals(True)
        combo.clear()
        combo.addItem('', '')
        for field in self.fields:
            combo.addItem(field, field)
        combo.blockSignals(False)
        self._set_combo_value(combo, current)

    def _label_widget_parts(self, widget):
        return (
            getattr(widget, 'label_combo', None),
            getattr(widget, 'label_size_spin', None),
            getattr(widget, 'label_detail_button', None),
        )

    def update_label_field_state(self, combo, detail_button):
        if combo is None or detail_button is None:
            return
        has_expression = bool((detail_button.property('label_expression') or '').strip())
        if has_expression:
            self._set_combo_value(combo, '詳細設定有')
        elif combo.currentText() == '詳細設定有':
            self._set_combo_value(combo, '')
        combo.setEnabled(True)
        combo.setProperty('detail_locked', has_expression)
        combo.setStyleSheet('background-color: #eeeeee; color: #777777;' if has_expression else '')

    def eventFilter(self, obj, event):
        if getattr(obj, 'property', None) and obj.property('detail_locked'):
            blocked_events = (
                QEvent.MouseButtonPress,
                QEvent.MouseButtonDblClick,
                QEvent.Wheel,
                QEvent.KeyPress,
            )
            if event.type() in blocked_events:
                if event.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick):
                    QMessageBox.information(self, 'ラベル', '詳細設定がされています。')
                return True
        return super().eventFilter(obj, event)

    def refresh_label_field_choices(self):
        if not hasattr(self, 'layers_table'):
            return
        for row in range(self.layers_table.rowCount()):
            if self._row_type(row) != 'layer':
                continue
            combo = self.layers_table.cellWidget(row, 3)
            detail_button = self.layers_table.cellWidget(row, 4)
            if combo is None:
                continue
            current = combo.currentData() or combo.currentText()
            self._populate_label_combo(combo, current)
            self.update_label_field_state(combo, detail_button)

    def create_label_field_combo(self, values=None):
        values = values or {}
        combo = QComboBox()
        combo.setMinimumWidth(dpi_px(120))
        self._populate_label_combo(combo, values.get('label_field') or values.get('label') or '')
        combo.installEventFilter(self)
        return combo

    def create_label_size_spin(self, values=None):
        values = values or {}
        size_spin = QDoubleSpinBox()
        size_spin.setRange(0.1, 99.9)
        size_spin.setDecimals(1)
        size_spin.setSingleStep(0.5)
        size_spin.setSuffix(' mm')
        size_spin.setValue(float(values.get('label_size_mm') or 3.0))
        size_spin.setStyleSheet(_compact_spinbox_style())
        return size_spin

    def create_symbol_size_spin(self, values=None):
        values = values or {}
        size_spin = QDoubleSpinBox()
        size_spin.setRange(0.1, 99.9)
        size_spin.setDecimals(1)
        size_spin.setSingleStep(0.5)
        size_spin.setSuffix(' mm')
        size_spin.setValue(float(values.get('size_mm') or 2.0))
        size_spin.setStyleSheet(_compact_spinbox_style())
        return size_spin

    def create_label_detail_button(self, field_combo, values=None):
        values = values or {}
        detail_button = QPushButton('詳細')
        detail_button.setMinimumWidth(dpi_px(44))
        detail_button.setProperty('label_expression', values.get('label_expression') or '')
        detail_button.clicked.connect(
            lambda checked=False, button=detail_button, combo=field_combo: self.edit_label_expression(button, combo)
        )
        self.update_label_field_state(field_combo, detail_button)
        return detail_button

    def edit_label_expression(self, button, field_combo=None):
        expression = button.property('label_expression') or ''
        dialog = LabelExpressionDialog(expression, self)
        if dialog.exec_() == QDialog.Accepted:
            button.setProperty('label_expression', dialog.expression())
            self.update_label_field_state(field_combo, button)

    def load_fields_from_csv(self, path):
        try:
            with open(path, 'r', encoding='utf-8-sig', newline='') as handle:
                reader = csv.reader(handle)
                self.fields = next(reader, [])
                self._populate_field_choices()
        except Exception as exc:
            QMessageBox.warning(self, 'レイヤセット作成', 'CSVの列名を読み込めませんでした: {0}'.format(exc))
            self.fields = []

    def add_layer_definition(self, values=None):
        values = values or {}
        if values.get('type') == 'group':
            self.add_group_definition(values)
            return
        row = self.layers_table.rowCount()
        self.layers_table.insertRow(row)

        enabled = QTableWidgetItem('ON')
        enabled.setCheckState(Qt.Checked if values.get('enabled', True) else Qt.Unchecked)
        enabled.setData(Qt.UserRole, 'layer')
        self.layers_table.setItem(row, 0, enabled)

        level_item = QTableWidgetItem('---')
        level_item.setFlags(level_item.flags() & ~Qt.ItemIsEditable)
        level_item.setBackground(QColor(230, 230, 230))
        level_item.setForeground(QColor(120, 120, 120))
        self.layers_table.setItem(row, 1, level_item)

        self.layers_table.setItem(row, 2, QTableWidgetItem(values.get('name') or '新しいレイヤ'))

        label_combo = self.create_label_field_combo(values)
        label_detail_button = self.create_label_detail_button(label_combo, values)
        self.layers_table.setCellWidget(row, 3, label_combo)
        self.layers_table.setCellWidget(row, 4, label_detail_button)

        condition_item = QTableWidgetItem(self._condition_summary(values.get('condition')))
        condition_item.setFlags(condition_item.flags() & ~Qt.ItemIsEditable)
        condition_item.setToolTip('クリックして条件を設定')
        self.layers_table.setItem(row, 5, condition_item)

        self.layers_table.setCellWidget(row, 6, self.create_label_size_spin(values))

        label_text_color = values.get('label_text_color') or '0,0,0,255'
        label_text_color_button = QPushButton('選択')
        label_text_color_button.setProperty('color_rgba', label_text_color)
        label_text_color_button.setStyleSheet(_color_button_style(label_text_color))
        label_text_color_button.clicked.connect(lambda checked=False, button=label_text_color_button: self.choose_layer_color(button))
        self.layers_table.setCellWidget(row, 7, label_text_color_button)

        symbol_combo = QComboBox()
        for symbol in ('circle', 'square', 'triangle', 'diamond', 'cross'):
            symbol_combo.addItem(symbol)
        symbol_combo.setCurrentText(values.get('shape') or 'circle')
        self.layers_table.setCellWidget(row, 8, symbol_combo)

        self.layers_table.setCellWidget(row, 9, self.create_symbol_size_spin(values))

        symbol_color = values.get('symbol_color') or values.get('color') or '0,112,255,255'
        symbol_color_button = QPushButton('選択')
        symbol_color_button.setProperty('color_rgba', symbol_color)
        symbol_color_button.setStyleSheet(_color_button_style(symbol_color))
        symbol_color_button.clicked.connect(lambda checked=False, button=symbol_color_button: self.choose_layer_color(button))
        self.layers_table.setCellWidget(row, 10, symbol_color_button)

        transparency_spin = QSpinBox()
        transparency_spin.setRange(0, 100)
        transparency_spin.setSuffix('%')
        transparency_value = values.get('label_background_transparency')
        transparency_spin.setValue(int(float(transparency_value if transparency_value is not None else 80)))
        transparency_spin.setStyleSheet(_compact_spinbox_style())
        self.layers_table.setCellWidget(row, 11, transparency_spin)

        label_background_color = values.get('label_background_color') or values.get('color') or '0,112,255,255'
        label_background_color_button = QPushButton('選択')
        label_background_color_button.setProperty('color_rgba', label_background_color)
        label_background_color_button.setStyleSheet(_color_button_style(label_background_color))
        label_background_color_button.clicked.connect(lambda checked=False, button=label_background_color_button: self.choose_layer_color(button))
        self.layers_table.setCellWidget(row, 12, label_background_color_button)
        self.condition_configs[row] = values.get('condition') or {'action': 'include', 'match_mode': 'all', 'rules': []}
        self.schedule_layer_table_column_adjustment()
        self.schedule_run_button_text_update()

    def add_group_definition(self, values=None):
        values = values or {}
        row = self.layers_table.rowCount()
        self.layers_table.insertRow(row)

        enabled = QTableWidgetItem('ON')
        enabled.setCheckState(Qt.Checked if values.get('enabled', True) else Qt.Unchecked)
        enabled.setData(Qt.UserRole, 'group')
        self.layers_table.setItem(row, 0, enabled)

        level_combo = QComboBox()
        allowed_levels = self.allowed_group_levels(row)
        for level in allowed_levels:
            level_combo.addItem(str(level), level)
        requested_level = int(values.get('level') or 1)
        if requested_level not in allowed_levels:
            requested_level = 1
        level_combo.setCurrentIndex(level_combo.findData(requested_level))
        self.layers_table.setCellWidget(row, 1, level_combo)

        name_item = QTableWidgetItem(values.get('name') or '新しいグループ')
        name_item.setData(Qt.UserRole, 'group')
        self.layers_table.setItem(row, 2, name_item)

        for column in range(3, 13):
            item = QTableWidgetItem('---')
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setBackground(QColor(230, 230, 230))
            item.setForeground(QColor(120, 120, 120))
            self.layers_table.setItem(row, column, item)
        self.refresh_group_level_choices()
        self.schedule_layer_table_column_adjustment()
        self.schedule_run_button_text_update()

    def duplicate_layer_definition(self):
        row = self.layers_table.currentRow()
        if row < 0:
            return
        config = self._layer_config_for_row(row)
        config['name'] = '{0}_copy'.format(config['name'])
        if config.get('type') == 'group':
            self.add_group_definition(config)
        else:
            self.add_layer_definition(config)

    def remove_layer_definition(self):
        row = self.layers_table.currentRow()
        if row < 0:
            return
        removed_row = row
        old_configs = dict(self.condition_configs)
        self.layers_table.removeRow(row)
        new_configs = {}
        for row in range(self.layers_table.rowCount()):
            old_row = row if row < removed_row else row + 1
            new_configs[row] = old_configs.get(old_row) or {'action': 'include', 'match_mode': 'all', 'rules': []}
        self.condition_configs = new_configs
        self.refresh_group_level_choices()
        self.schedule_run_button_text_update()

    def move_selected_row_up(self):
        self._move_selected_row(-1)

    def move_selected_row_down(self):
        self._move_selected_row(1)

    def _move_selected_row(self, offset):
        row = self.layers_table.currentRow()
        target = row + offset
        if row < 0 or target < 0 or target >= self.layers_table.rowCount():
            return
        configs = self.all_layer_configs()
        configs[row], configs[target] = configs[target], configs[row]
        self._set_layer_configs(configs)
        self.layers_table.selectRow(target)

    def _set_layer_configs(self, configs):
        self.layers_table.setRowCount(0)
        self.condition_configs = {}
        for config in configs:
            if config.get('type') == 'group':
                self.add_group_definition(config)
            else:
                self.add_layer_definition(config)
        self.refresh_group_level_choices()
        self.schedule_run_button_text_update()

    def previous_group_level(self, row):
        for index in range(row - 1, -1, -1):
            if self._row_type(index) == 'group':
                return self._group_level_for_row(index)
        return 0

    def allowed_group_levels(self, row):
        return list(range(1, self.previous_group_level(row) + 2))

    def refresh_group_level_choices(self):
        for row in range(self.layers_table.rowCount()):
            if self._row_type(row) != 'group':
                continue
            combo = self.layers_table.cellWidget(row, 1)
            current = combo.currentData() if combo is not None else 1
            allowed = self.allowed_group_levels(row)
            if current not in allowed:
                current = 1
            if combo is None:
                combo = QComboBox()
                self.layers_table.setCellWidget(row, 1, combo)
            combo.blockSignals(True)
            combo.clear()
            for level in allowed:
                combo.addItem(str(level), level)
            combo.setCurrentIndex(combo.findData(current))
            combo.blockSignals(False)

    def handle_layer_item_changed(self, item):
        if item is not None and item.column() == 0:
            self.schedule_run_button_text_update()

    def choose_layer_color(self, button):
        current = _rgba_to_qcolor(button.property('color_rgba'))
        selected = QColorDialog.getColor(
            current,
            self,
            'レイヤ色を選択',
            QColorDialog.ShowAlphaChannel,
        )
        if not selected.isValid():
            return
        rgba = _qcolor_to_rgba(selected)
        button.setProperty('color_rgba', rgba)
        button.setStyleSheet(_color_button_style(rgba))

    def handle_layer_cell_clicked(self, row, column):
        if column == 5 and self._row_type(row) != 'group':
            self.edit_layer_condition(row)

    def edit_layer_condition(self, row):
        if row < 0:
            QMessageBox.information(self, 'レイヤセット作成', '条件を設定するレイヤを選択してください。')
            return
        if not self.fields and self.csv_path_edit.text().strip():
            self.load_fields_from_csv(self.csv_path_edit.text().strip())
        if not self.fields:
            QMessageBox.warning(self, 'レイヤセット作成', '先に入力CSVを選択してください。')
            return
        current = self.condition_configs.get(row) or {'action': 'include', 'match_mode': 'all', 'rules': []}
        dialog = LayerConditionDialog(
            self.fields,
            rules=current.get('rules'),
            action=current.get('action', 'include'),
            match_mode=current.get('match_mode', 'all'),
            parent=self,
        )
        if dialog.exec_() == QDialog.Accepted:
            self.condition_configs[row] = dialog.config()
            condition_item = QTableWidgetItem(self._condition_summary(self.condition_configs[row]))
            condition_item.setFlags(condition_item.flags() & ~Qt.ItemIsEditable)
            condition_item.setToolTip('クリックして条件を設定')
            self.layers_table.setItem(row, 5, condition_item)

    def _condition_summary(self, condition):
        rules = (condition or {}).get('rules') or []
        if not rules:
            return '条件なし'
        return '{0}件'.format(len(rules))

    def _row_type(self, row):
        item = self.layers_table.item(row, 0)
        return item.data(Qt.UserRole) if item is not None else 'layer'

    def _group_level_for_row(self, row):
        combo = self.layers_table.cellWidget(row, 1)
        if combo is None:
            return 1
        value = combo.currentData()
        return int(value or 1)

    def _layer_config_for_row(self, row):
        enabled_item = self.layers_table.item(row, 0)
        row_type = self._row_type(row)
        if row_type == 'group':
            return {
                'type': 'group',
                'enabled': enabled_item.checkState() == Qt.Checked if enabled_item else True,
                'level': self._group_level_for_row(row),
                'name': _table_text(self.layers_table, row, 2) or 'group_{0}'.format(row + 1),
            }

        label_combo = self.layers_table.cellWidget(row, 3)
        label_detail_button = self.layers_table.cellWidget(row, 4)
        label_size_spin = self.layers_table.cellWidget(row, 6)
        label_text_color_button = self.layers_table.cellWidget(row, 7)
        symbol_combo = self.layers_table.cellWidget(row, 8)
        symbol_size_spin = self.layers_table.cellWidget(row, 9)
        symbol_color_button = self.layers_table.cellWidget(row, 10)
        transparency_spin = self.layers_table.cellWidget(row, 11)
        label_background_color_button = self.layers_table.cellWidget(row, 12)
        size_mm = symbol_size_spin.value() if symbol_size_spin else 2.0
        label_expression = label_detail_button.property('label_expression') if label_detail_button else ''
        label_expression = label_expression or ''
        label_field = ''
        if not label_expression.strip() and label_combo:
            label_field = label_combo.currentData() or label_combo.currentText()
        return {
            'type': 'layer',
            'enabled': enabled_item.checkState() == Qt.Checked if enabled_item else True,
            'name': _table_text(self.layers_table, row, 2) or 'layer_{0}'.format(row + 1),
            'label_field': label_field,
            'label_size_mm': label_size_spin.value() if label_size_spin else 3.0,
            'label_text_color': label_text_color_button.property('color_rgba') if label_text_color_button else '0,0,0,255',
            'label_background_color': label_background_color_button.property('color_rgba') if label_background_color_button else '0,112,255,255',
            'label_expression': label_expression,
            'label_background_transparency': transparency_spin.value() if transparency_spin else 80,
            'symbol_color': symbol_color_button.property('color_rgba') if symbol_color_button else '0,112,255,255',
            'color': symbol_color_button.property('color_rgba') if symbol_color_button else '0,112,255,255',
            'shape': symbol_combo.currentText() if symbol_combo else 'circle',
            'size_mm': size_mm,
            'condition': self.condition_configs.get(row) or {'action': 'include', 'match_mode': 'all', 'rules': []},
        }

    def layer_configs(self):
        return [
            self._layer_config_for_row(row)
            for row in range(self.layers_table.rowCount())
            if self._layer_config_for_row(row).get('enabled')
        ]

    def all_layer_configs(self):
        return [
            self._layer_config_for_row(row)
            for row in range(self.layers_table.rowCount())
        ]

    def find_duplicate_enabled_names(self):
        seen = {}
        duplicates = []
        for row in range(self.layers_table.rowCount()):
            config = self._layer_config_for_row(row)
            if not config.get('enabled'):
                continue
            name = (config.get('name') or '').strip()
            if not name:
                continue
            key = name.casefold()
            if key in seen:
                duplicates.append(name)
            else:
                seen[key] = row
        return duplicates

    def validate_unique_names(self):
        duplicates = self.find_duplicate_enabled_names()
        if not duplicates:
            return True
        names = '\n'.join('- {0}'.format(name) for name in sorted(set(duplicates), key=str.casefold))
        QMessageBox.warning(
            self,
            'レイヤセット作成',
            'レイヤ名またはレイヤグループ名が重複しています。\nGeoPackage保存時に上書きされるため、別の名前にしてください。\n\n{0}'.format(names),
        )
        return False

    def accept(self):
        if not self.validate_unique_names():
            return
        super().accept()

    def csv_path(self):
        return self.csv_path_edit.text().strip()

    def output_path(self):
        return self.output_path_edit.text().strip()

    def x_field(self):
        return self.x_field_combo.currentText().strip()

    def y_field(self):
        return self.y_field_combo.currentText().strip()

    def crs(self):
        return self.crs_combo.currentText().strip() or 'EPSG:4326'

    def output_crs(self):
        return self.output_crs_combo.currentText().strip() or self.crs()

    def add_to_project(self):
        return True

    def preset_path(self):
        return default_json_path('layer_sets_default', 'preset.json')

    def config_folder(self):
        return tool_config_folder('layer_sets_default')

    def current_config(self):
        return {
            'version': 1,
            'preset': 'layer_sets_default',
            'tool': 'add_sets_layers',
            'input': {
                'csv_path': self.csv_path(),
                'x_field': self.x_field(),
                'y_field': self.y_field(),
                'crs': self.crs(),
            },
            'layers': self.all_layer_configs(),
            'layer_sets': {
                'group_selection': ['group1'],
                'selected_ward': '',
                'shape': 'circle',
                'size_mm': 2.0,
                'area_filter': {},
            },
            'output': {
                'gpkg_path': self.output_path(),
                'crs': self.output_crs(),
                'layer_name': '',
                'add_to_project': self.add_to_project(),
            },
            'log': {
                'save_to_file': False,
                'path': '',
            },
        }

    def apply_config(self, config):
        input_config = config.get('input') or {}
        output_config = config.get('output') or {}
        self.csv_path_edit.setText(input_config.get('csv_path') or '')
        self.output_path_edit.setText(output_config.get('gpkg_path') or '')
        selected_x = input_config.get('x_field') or '世界_10進_X'
        selected_y = input_config.get('y_field') or '世界_10進_Y'
        selected_crs = input_config.get('crs') or 'EPSG:4326'
        selected_output_crs = output_config.get('crs') or selected_crs
        self._set_combo_value(self.x_field_combo, selected_x)
        self._set_combo_value(self.y_field_combo, selected_y)
        self._populate_crs_choices(selected_crs)
        self._populate_crs_choices(selected_output_crs, self.output_crs_combo)

        if self.csv_path_edit.text().strip():
            self.load_fields_from_csv(self.csv_path_edit.text().strip())
            self._set_combo_value(self.x_field_combo, selected_x)
            self._set_combo_value(self.y_field_combo, selected_y)

        self.layers_table.setRowCount(0)
        self.condition_configs = {}
        layers = config.get('layers') or (config.get('layer_sets') or {}).get('layers') or []
        if not layers:
            layers = [{
                'enabled': True,
                'name': '新しいレイヤ',
                'label_field': '',
                'label_size_mm': 3.0,
                'label_text_color': '0,0,0,255',
                'label_background_color': '0,112,255,255',
                'label_expression': '',
                'label_background_transparency': 80,
                'symbol_color': '0,112,255,255',
                'color': '0,112,255,255',
                'shape': 'circle',
                'size_mm': 2.0,
                'condition': {'action': 'include', 'match_mode': 'all', 'rules': []},
            }]
        for layer_config in layers:
            self.add_layer_definition(layer_config)
        self.schedule_layer_table_column_adjustment()

    def load_preset(self):
        path = self.preset_path()
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            QMessageBox.information(
                self,
                'レイヤセット作成',
                'このプロジェクトには保存済みプリセットがまだありません。\n'
                '現在の設定を保存する場合は「プリセット更新」を押してください。\n\n'
                '保存先:\n{0}'.format(path),
            )
            return
        try:
            with open(path, 'r', encoding='utf-8') as handle:
                self.apply_config(json.load(handle))
            QMessageBox.information(self, 'レイヤセット作成', 'プリセットを呼び出しました。')
        except Exception as exc:
            QMessageBox.warning(self, 'レイヤセット作成', 'プリセットを読み込めませんでした: {0}'.format(exc))

    def update_preset(self):
        if not self.validate_unique_names():
            return
        path = self.preset_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as handle:
                json.dump(self.current_config(), handle, ensure_ascii=False, indent=2)
                handle.write('\n')
            QMessageBox.information(self, 'レイヤセット作成', 'プリセットを更新しました。')
        except Exception as exc:
            QMessageBox.warning(self, 'レイヤセット作成', 'プリセットを更新できませんでした: {0}'.format(exc))

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
            QMessageBox.information(self, 'レイヤセット作成', '設定を読み込みました。')
        except Exception as exc:
            QMessageBox.warning(self, 'レイヤセット作成', '設定を読み込めませんでした: {0}'.format(exc))

    def save_config_file(self):
        if not self.validate_unique_names():
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            '設定を保存',
            default_json_path('layer_sets_default'),
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
            QMessageBox.information(self, 'レイヤセット作成', '設定を保存しました。')
        except Exception as exc:
            QMessageBox.warning(self, 'レイヤセット作成', '設定を保存できませんでした: {0}'.format(exc))

    # Compatibility with the former fixed-group dialog.
    def selected_group_keys(self):
        return ['group1']

    def area_filter_values(self):
        return {}
