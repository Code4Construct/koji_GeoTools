# -*- coding: utf-8 -*-

import os

from qgis.PyQt.QtCore import QCoreApplication, QSettings, Qt, QTranslator
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QAction,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .add_sets_layers.add_sets_layers import Add_Sets_Layers
from .geotools_runner import ConfigurableToolRunner
from .kgt_paths import project_kgt_root
from .merge_features_in_polygon.merge_features_in_polygon import (
    MergeFeaturesInPolygon,
)
from .study_area_builder.study_area_builder import StudyAreaBuilder
from .ui_scaling import display_metrics_text, dpi_px


class KojiGeoToolsDialog(QDialog):
    """Single-screen launcher for Koji GeoTools."""

    def __init__(self, tools, run_callback, config_runner, parent=None):
        super().__init__(parent)
        self.tools = tools
        self.run_callback = run_callback
        self.config_runner = config_runner

        self.setWindowTitle('Koji GeoTools')
        self.setMinimumWidth(dpi_px(500))
        self.resize(dpi_px(620), dpi_px(600))

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(dpi_px(18), dpi_px(18), dpi_px(18), dpi_px(18))
        main_layout.setSpacing(dpi_px(12))

        title_row = QHBoxLayout()
        title_row.setSpacing(dpi_px(10))

        brand_icon = QLabel()
        brand_pixmap = QIcon(os.path.join(os.path.dirname(__file__), 'icon.png')).pixmap(dpi_px(30), dpi_px(30))
        brand_icon.setPixmap(brand_pixmap)
        brand_icon.setFixedSize(dpi_px(34), dpi_px(34))
        brand_icon.setAlignment(Qt.AlignCenter)

        title_block = QVBoxLayout()
        title_block.setContentsMargins(0, 0, 0, 0)
        title_block.setSpacing(dpi_px(1))

        title = QLabel('Koji GeoTools')
        title_font = title.font()
        title_font.setPointSize(15)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setStyleSheet('color: #183a2f; letter-spacing: 0px;')

        lead = QLabel('使用したい機能をクリックしてください。')
        lead.setStyleSheet('color: #66726c;')

        metrics_label = QLabel(display_metrics_text())
        metrics_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        metrics_label.setStyleSheet('color: #66726c;')

        title_block.addWidget(title)
        title_block.addWidget(lead)

        title_row.addWidget(brand_icon)
        title_row.addLayout(title_block)
        title_row.addStretch(1)
        title_row.addWidget(metrics_label)
        main_layout.addLayout(title_row)

        accent_line = QFrame()
        accent_line.setFixedHeight(dpi_px(2))
        accent_line.setStyleSheet('background: #2f8f5b; border: none;')
        main_layout.addWidget(accent_line)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_content = QWidget()
        self.tools_layout = QGridLayout(scroll_content)
        self.tools_layout.setContentsMargins(0, 0, 0, 0)
        self.tools_layout.setSpacing(dpi_px(10))

        for index, tool in enumerate(self.tools):
            self.tools_layout.addWidget(self._create_tool_row(tool), index, 0)

        self.tools_layout.setColumnStretch(0, 1)
        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area, 1)

        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)

    def _create_tool_row(self, tool):
        row = QPushButton()
        row.setMinimumHeight(dpi_px(118))
        row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        row.setCursor(Qt.PointingHandCursor)
        row.clicked.connect(lambda checked=False, key=tool['key']: self.run_callback(key))
        row.setStyleSheet(
            'QPushButton {{ text-align: left; border: {0}px solid #c8c8c8; border-radius: {1}px; background: #f7f7f7; }}'
            'QPushButton:hover {{ background: #eef5ff; border-color: #7aa7d9; }}'
            'QPushButton:pressed {{ background: #e0edf9; }}'
            'QLabel {{ border: none; background: transparent; }}'
            .format(dpi_px(1), dpi_px(4))
        )

        layout = QHBoxLayout(row)
        layout.setContentsMargins(dpi_px(12), dpi_px(10), dpi_px(12), dpi_px(10))
        layout.setSpacing(dpi_px(12))

        icon_label = QLabel()
        icon = QIcon(tool['icon_path'])
        icon_size = dpi_px(64)
        icon_box = dpi_px(72)
        icon_label.setPixmap(icon.pixmap(icon_size, icon_size))
        icon_label.setFixedSize(icon_box, icon_box)
        icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon_label)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(dpi_px(4))

        name_label = QLabel(tool['text'])
        name_label.setStyleSheet('font-weight: 600;')
        description_label = QLabel(tool['description'])
        description_label.setWordWrap(True)
        description_label.setMinimumHeight(description_label.fontMetrics().lineSpacing() * 3 + dpi_px(6))
        description_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

        text_layout.addWidget(name_label)
        text_layout.addWidget(description_label)
        layout.addLayout(text_layout, 1)
        return row


class KojiGeoTools:
    """Single-entry wrapper plugin for selected Koji GeoTools."""

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.child_plugins = {}
        self.tool_definitions = []
        self.config_runner = ConfigurableToolRunner(iface)
        self.dlg = None
        self.menu_title = self.tr(u'&Koji GeoTools')

        locale = QSettings().value('locale/userLocale', '')[0:2]
        locale_path = os.path.join(
            self.plugin_dir,
            'i18n',
            'KojiGeoTools_{}.qm'.format(locale),
        )

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)
            QCoreApplication.installTranslator(self.translator)

    def tr(self, message):
        return QCoreApplication.translate('KojiGeoTools', message)

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, 'icon.png')
        icon = QIcon(icon_path)

        self._add_tool(
            key='add_sets_layers',
            text=self.tr(u'レイヤセット作成'),
            description=self.tr(u'CSVデータから施設配置検討用のレイヤセットを作成します。座標フィールド、CRS、出力先GeoPackage、プロジェクトへの追加有無を設定できます。'),
            plugin_class=Add_Sets_Layers,
            icon_path=os.path.join(self.plugin_dir, 'add_sets_layers', 'icon.png'),
        )
        self._add_tool(
            key='study_area_builder',
            text=self.tr(u'調査エリア設定'),
            description=self.tr(u'選択地点や地図上の座標を中心に、任意の半径で調査エリア円を作成・保存できます。行政区域と結合した調査エリアの設定にも対応しています。'),
            plugin_class=StudyAreaBuilder,
            icon_path=os.path.join(self.plugin_dir, 'study_area_builder', 'icon.png'),
        )
        self._add_tool(
            key='merge_features_in_polygon',
            text=self.tr(u'ポリゴン内の地物抽出'),
            description=self.tr(u'選択ポリゴン内にある表示中のポイント地物・ポリゴン地物を抽出して統合します。スタイル継承やsource FID付与にも対応します。'),
            plugin_class=MergeFeaturesInPolygon,
            icon_path=os.path.join(self.plugin_dir, 'merge_features_in_polygon', 'icon.png'),
        )
        self.main_action = QAction(icon, self.tr(u'Koji GeoTools'), self.iface.mainWindow())
        self.main_action.triggered.connect(self.show_dialog)
        self.iface.addToolBarIcon(self.main_action)
        self.iface.addPluginToMenu(self.menu_title, self.main_action)
        self.actions.append(self.main_action)

    def _add_tool(self, key, text, description, plugin_class, icon_path):
        self.tool_definitions.append({
            'key': key,
            'text': text,
            'description': description,
            'icon_path': icon_path,
        })
        self.child_plugins[key] = {
            'class': plugin_class,
            'instance': None,
            'text': text,
        }

    def unload(self):
        for action in self.actions:
            self.iface.removePluginMenu(self.menu_title, action)
            self.iface.removeToolBarIcon(action)

        if self.dlg is not None:
            self.dlg.close()
            self.dlg = None

    def show_dialog(self):
        project_kgt_root()
        if self.dlg is None:
            self.dlg = KojiGeoToolsDialog(
                self.tool_definitions,
                self.run_tool,
                self.config_runner,
                self.iface.mainWindow(),
            )

        self.dlg.show()
        self.dlg.raise_()
        self.dlg.activateWindow()

    def run_tool(self, key):
        tool = self.child_plugins.get(key)
        if tool is None:
            QMessageBox.warning(
                self.iface.mainWindow(),
                self.tr(u'Koji GeoTools'),
                self.tr(u'The selected tool was not found.'),
            )
            return

        launcher_dialog = self.dlg
        if launcher_dialog is not None:
            launcher_dialog.close()
            self.dlg = None

        try:
            if tool['instance'] is None:
                tool['instance'] = tool['class'](self.iface)
                if hasattr(tool['instance'], 'first_start'):
                    tool['instance'].first_start = True

            tool['instance'].run()
        except Exception as exc:  # pragma: no cover - shown inside QGIS
            if launcher_dialog is not None:
                self.dlg = launcher_dialog
                self.dlg.show()
                self.dlg.raise_()
                self.dlg.activateWindow()
            QMessageBox.critical(
                self.iface.mainWindow(),
                self.tr(u'Koji GeoTools'),
                self.tr(u'Failed to start tool: {0}').format(exc),
            )
