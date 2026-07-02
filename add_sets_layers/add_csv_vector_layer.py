# -*- coding: utf-8 -*-
import os

from qgis.PyQt.QtWidgets import QInputDialog, QFileDialog, QMessageBox
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtCore import QSizeF
from qgis.core import (
    QgsVectorLayer,
    QgsProject,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsMarkerSymbol,
    QgsSingleSymbolRenderer,
    QgsPalLayerSettings,
    QgsTextFormat,
    QgsTextBackgroundSettings,
    QgsUnitTypes,
    QgsVectorLayerSimpleLabeling,
    QgsRuleBasedLabeling,
    QgsVectorFileWriter
)

# ==========================================
# ここを編集してください
# 「選んだ区の外」で除外したい施設名称キーワード
# この文字を含む施設は、選択した区の外では表示しません
# 選択した区の中では表示します
# ==========================================
EXCLUDED_OUTSIDE_WARD_NAME_KEYWORDS = [
    "消防署"
]

WARD_NAMES = [
    "都島区", "福島区", "此花区", "西区", "港区", "大正区", "天王寺区", "浪速区",
    "西淀川区", "東淀川区", "東成区", "生野区", "旭区", "城東区", "阿倍野区", "住吉区",
    "東住吉区", "西成区", "淀川区", "鶴見区", "住之江区", "平野区", "北区", "中央区"
]


def get_or_create_group(root, group_name):
    group = root.findGroup(group_name)
    if group is None:
        group = root.addGroup(group_name)
    return group


def rgba_string_to_qcolor(color_rgba, background_alpha=51):
    """
    '255,0,0,255' のような文字列を QColor に変換
    background_alpha=51 は約20%不透明
    """
    parts = [p.strip() for p in color_rgba.split(",")]
    r = int(parts[0]) if len(parts) > 0 else 0
    g = int(parts[1]) if len(parts) > 1 else 0
    b = int(parts[2]) if len(parts) > 2 else 0
    a = int(parts[3]) if len(parts) > 3 else 255

    if background_alpha is None:
        return QColor(r, g, b, a)
    return QColor(r, g, b, background_alpha)


def apply_symbol(layer, shape, color_rgba, size_mm):
    symbol = QgsMarkerSymbol.createSimple({
        'name': shape,
        'color': color_rgba,
        'outline_color': '0,0,0,255',
        'outline_width': '0.15',
        'outline_width_unit': 'MM',
        'size': str(size_mm),
        'size_unit': 'MM'
    })
    renderer = QgsSingleSymbolRenderer(symbol)
    layer.setRenderer(renderer)


def transparency_to_alpha(transparency_percent):
    try:
        transparency = float(transparency_percent)
    except (TypeError, ValueError):
        transparency = 80.0
    transparency = max(0.0, min(100.0, transparency))
    return int(round(255 * (100.0 - transparency) / 100.0))


def make_text_format_with_background(color_rgba, size_mm=3, background_transparency=80, text_color_rgba='0,0,0,255'):
    text_format = QgsTextFormat()
    text_format.setSize(float(size_mm or 3))
    text_format.setSizeUnit(QgsUnitTypes.RenderMillimeters)
    text_format.setColor(rgba_string_to_qcolor(text_color_rgba or '0,0,0,255', background_alpha=None))

    bg = QgsTextBackgroundSettings()
    bg.setEnabled(True)
    bg.setType(QgsTextBackgroundSettings.ShapeRectangle)
    bg.setFillColor(rgba_string_to_qcolor(color_rgba, background_alpha=transparency_to_alpha(background_transparency)))
    bg.setStrokeColor(QColor(0, 0, 0, 0))

    bg.setSizeType(QgsTextBackgroundSettings.SizeBuffer)
    bg.setSize(QSizeF(0.8, 0.5))
    bg.setSizeUnit(QgsUnitTypes.RenderMillimeters)

    bg.setRadii(QSizeF(0.4, 0.4))
    bg.setRadiiUnit(QgsUnitTypes.RenderMillimeters)

    text_format.setBackground(bg)
    return text_format


def apply_simple_label(layer, label_expr, color_rgba, size_mm=3, background_transparency=80, text_color_rgba='0,0,0,255'):
    settings = QgsPalLayerSettings()
    settings.enabled = True
    settings.isExpression = True
    settings.fieldName = label_expr

    text_format = make_text_format_with_background(color_rgba, size_mm, background_transparency, text_color_rgba)
    settings.setFormat(text_format)

    labeling = QgsVectorLayerSimpleLabeling(settings)
    layer.setLabeling(labeling)
    layer.setLabelsEnabled(True)


def apply_rule_based_label(layer, label_expr, color_rgba, description="rule label", size_mm=3, background_transparency=80, text_color_rgba='0,0,0,255'):
    settings = QgsPalLayerSettings()
    settings.enabled = True
    settings.isExpression = True
    settings.fieldName = label_expr

    text_format = make_text_format_with_background(color_rgba, size_mm, background_transparency, text_color_rgba)
    settings.setFormat(text_format)

    root_rule = QgsRuleBasedLabeling.Rule(QgsPalLayerSettings())
    rule = QgsRuleBasedLabeling.Rule(settings)
    rule.setDescription(description)
    root_rule.appendChild(rule)

    labeling = QgsRuleBasedLabeling(root_rule)
    layer.setLabeling(labeling)
    layer.setLabelsEnabled(True)


def build_name_not_contains_all_expression(field_name, keywords):
    valid_keywords = [k for k in keywords if str(k).strip()]
    if not valid_keywords:
        return "TRUE"

    parts = []
    for keyword in valid_keywords:
        safe_kw = keyword.replace("'", "''")
        parts.append(f"\"{field_name}\" NOT LIKE '%{safe_kw}%'")
    return "(" + " AND ".join(parts) + ")"


def build_field_is_empty_expression(field_name):
    """
    指定フィールドが NULL または空文字または空白のみ
    のとき TRUE になる式を返す
    """
    return f'( "{field_name}" IS NULL OR trim("{field_name}") = \'\' )'


def build_total_floor_area_expression(area_filter):
    if not area_filter:
        return ""

    min_area = area_filter.get('min')
    max_area = area_filter.get('max')
    conditions = [
        '"延床面積_平方メートル" IS NOT NULL',
        'trim("延床面積_平方メートル") != \'\'',
    ]
    if min_area is not None:
        conditions.append(f'to_real("延床面積_平方メートル") >= {int(min_area)}')
    if max_area is not None:
        conditions.append(f'to_real("延床面積_平方メートル") < {int(max_area)}')

    if len(conditions) == 2:
        return ""
    return " AND ".join(f"({condition})" for condition in conditions)


def build_total_floor_area_group_suffix(area_filter):
    if not area_filter:
        return ""

    min_area = area_filter.get('min')
    max_area = area_filter.get('max')
    if min_area is not None and max_area is not None:
        return f"_{int(min_area)}㎡ｰ{int(max_area)}㎡"
    if min_area is not None:
        return f"_{int(min_area)}㎡以上"
    if max_area is not None:
        return f"_{int(max_area)}㎡未満"
    return ""


def combine_filter_parts(*filter_parts):
    parts = [part for part in filter_parts if part and part.strip()]
    if not parts:
        return ""
    return " AND ".join(f"({part})" for part in parts)


def create_five_layers_in_group(project, iface, uri, group, shape, size_mm, extra_filter=""):
    common_general = '"施設区分" = \'一般施設\''
    common_rent = '"施設区分" = \'賃借施設\''

    if extra_filter.strip():
        general_base = f"({common_general}) AND ({extra_filter})"
        rent_base = f"({common_rent}) AND ({extra_filter})"
    else:
        general_base = common_general
        rent_base = common_rent

    desired_display_order = [
        {
            "name": "賃借施設",
            "subset": rent_base,
            "color": "160,32,240,255",
            "label_expr": '\'賃:\' || "施設名称"',
            "rule_based_label": True
        },
        {
            "name": "一般施設_築45年以上",
            "subset": f"({general_base}) AND ((year(now()) - to_int(\"建築時期\")) >= 45)",
            "color": "255,0,0,255",
            "label_expr": '"施設名称" || \'：築\' || to_string(year(now()) - to_int("建築時期")) || \'年\'',
            "rule_based_label": False
        },
        {
            "name": "一般施設_築40年以上45年未満",
            "subset": f"({general_base}) AND ((year(now()) - to_int(\"建築時期\")) >= 40 AND (year(now()) - to_int(\"建築時期\")) < 45)",
            "color": "255,255,0,255",
            "label_expr": '"施設名称" || \'：築\' || to_string(year(now()) - to_int("建築時期")) || \'年\'',
            "rule_based_label": False
        },
        {
            "name": "一般施設_築35年以上40年未満",
            "subset": f"({general_base}) AND ((year(now()) - to_int(\"建築時期\")) >= 35 AND (year(now()) - to_int(\"建築時期\")) < 40)",
            "color": "0,0,255,255",
            "label_expr": '"施設名称" || \'：築\' || to_string(year(now()) - to_int("建築時期")) || \'年\'',
            "rule_based_label": False
        },
        {
            "name": "一般施設_築35年未満",
            "subset": f"({general_base}) AND ((year(now()) - to_int(\"建築時期\")) < 35)",
            "color": "0,0,0,255",
            "label_expr": '"施設名称" || \'：築\' || to_string(year(now()) - to_int("建築時期")) || \'年\'',
            "rule_based_label": False
        }
    ]

    insertion_order = list(reversed(desired_display_order))
    created_names = []

    for d in insertion_order:
        layer = QgsVectorLayer(uri, d["name"], "delimitedtext")

        if not layer.isValid():
            print(f"Layer failed to load: {d['name']}")
            continue

        project.addMapLayer(layer, False)
        group.insertLayer(0, layer)

        layer.setSubsetString(d["subset"])
        apply_symbol(layer, shape, d["color"], size_mm)

        if d["rule_based_label"]:
            apply_rule_based_label(layer, d["label_expr"], d["color"], "賃借施設ラベル")
        else:
            apply_simple_label(layer, d["label_expr"], d["color"])

        layer.triggerRepaint()
        layer.emitStyleChanged()
        iface.layerTreeView().refreshLayerSymbology(layer.id())

        created_names.append(d["name"])

    return desired_display_order, created_names


def select_csv_path(parent, start_dir):
    csv_path, _ = QFileDialog.getOpenFileName(
        parent,
        "CSVファイルを選択してください",
        start_dir,
        "CSV Files (*.csv);;All Files (*.*)"
    )
    return csv_path


def get_project_start_dir(project):
    project_path = project.fileName()
    if not project_path and hasattr(project, "absoluteFilePath"):
        project_path = project.absoluteFilePath()

    if project_path:
        project_path = os.path.abspath(project_path)
        if os.path.isfile(project_path):
            return os.path.dirname(project_path)
        if os.path.isdir(project_path):
            return project_path

    home_path = project.homePath() if hasattr(project, "homePath") else ""
    if home_path and os.path.isdir(home_path):
        return os.path.abspath(home_path)

    return os.path.expanduser("~")


def _quote_field(field_name):
    return '"{0}"'.format(str(field_name).replace('"', '""'))


def _quote_value(value):
    return "'{0}'".format(str(value).replace("'", "''"))


def apply_configured_label(layer, label_field, color_rgba, size_mm=3, label_expression='', background_transparency=80, text_color_rgba='0,0,0,255'):
    label_expr = (label_expression or '').strip()
    if not label_expr and label_field:
        label_expr = _quote_field(label_field)
    if not label_expr:
        return
    apply_simple_label(layer, label_expr, color_rgba, size_mm, background_transparency, text_color_rgba)


def _condition_expression(rule):
    field = rule.get('field')
    if not field:
        return ''
    field_expr = _quote_field(field)
    kind = rule.get('filter_kind') or 'text'
    condition = rule.get('condition') or 'contains'
    value = rule.get('value') or ''
    value2 = rule.get('value2') or ''

    if condition == 'empty':
        return '({0} IS NULL OR trim({0}) = \'\')'.format(field_expr)
    if condition == 'not_empty':
        return '({0} IS NOT NULL AND trim({0}) != \'\')'.format(field_expr)

    if kind in ('number', 'year_minus_number'):
        if kind == 'year_minus_number':
            numeric_field = '(year(now()) - to_real({0}))'.format(field_expr)
        else:
            numeric_field = 'to_real({0})'.format(field_expr)
        if condition == 'between':
            if value == '' or value2 == '':
                return ''
            return '({0} >= {1} AND {0} < {2})'.format(numeric_field, float(value), float(value2))
        operator_map = {
            'equals': '=',
            'not_equals': '!=',
            'greater_equal': '>=',
            'greater_than': '>',
            'less_equal': '<=',
            'less_than': '<',
        }
        operator = operator_map.get(condition)
        if operator and value != '':
            return '({0} {1} {2})'.format(numeric_field, operator, float(value))
        return ''

    if condition == 'equals':
        return '({0} = {1})'.format(field_expr, _quote_value(value))
    if condition == 'not_equals':
        return '({0} != {1})'.format(field_expr, _quote_value(value))
    if condition == 'contains':
        return '({0} LIKE {1})'.format(field_expr, _quote_value('%{0}%'.format(value)))
    if condition == 'not_contains':
        return '({0} NOT LIKE {1})'.format(field_expr, _quote_value('%{0}%'.format(value)))
    if condition == 'starts_with':
        return '({0} LIKE {1})'.format(field_expr, _quote_value('{0}%'.format(value)))
    if condition == 'ends_with':
        return '({0} LIKE {1})'.format(field_expr, _quote_value('%{0}'.format(value)))
    return ''


def build_layer_subset_expression(condition_config):
    rules = (condition_config or {}).get('rules') or []
    expressions = [_condition_expression(rule) for rule in rules]
    expressions = [expression for expression in expressions if expression]
    if not expressions:
        return ''

    joiner = ' OR ' if (condition_config or {}).get('match_mode') == 'any' else ' AND '
    expression = '(' + joiner.join(expressions) + ')'
    if (condition_config or {}).get('action') == 'exclude':
        return 'NOT {0}'.format(expression)
    return expression


def _csv_uri(csv_path, x_field, y_field, crs):
    csv_path_uri = csv_path.replace("\\", "/")
    return (
        f"file:///{csv_path_uri}"
        "?delimiter=,"
        f"&xField={x_field}"
        f"&yField={y_field}"
        f"&crs={crs}"
    )


def _write_layer_to_gpkg(layer, output_path, layer_name, transform_context, first_layer, output_crs=''):
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GPKG"
    options.layerName = layer_name
    options.fileEncoding = "UTF-8"
    if output_crs:
        destination_crs = QgsCoordinateReferenceSystem(output_crs)
        if destination_crs.isValid() and destination_crs != layer.crs():
            try:
                options.ct = QgsCoordinateTransform(layer.crs(), destination_crs, QgsProject.instance())
            except Exception:
                pass
    try:
        if first_layer:
            options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile
        else:
            options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
    except Exception:
        pass

    result = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer,
        output_path,
        transform_context,
        options,
    )
    if result[0] != QgsVectorFileWriter.NoError:
        raise Exception("GeoPackage保存エラー: {0}".format(result))


def run_configured_layers(
    iface,
    csv_path,
    output_path,
    x_field,
    y_field,
    crs,
    layer_configs,
    output_crs='',
    add_to_project=True,
):
    if not csv_path:
        raise Exception("入力CSVを選択してください。")
    if not os.path.exists(csv_path):
        raise Exception("入力CSVが見つかりません: {0}".format(csv_path))
    if not layer_configs:
        raise Exception("作成するレイヤを1つ以上設定してください。")

    seen_names = set()
    duplicate_names = []
    for config in layer_configs:
        if not config.get('enabled', True):
            continue
        name = (config.get('name') or '').strip()
        if not name:
            continue
        key = name.casefold()
        if key in seen_names:
            duplicate_names.append(name)
        else:
            seen_names.add(key)
    if duplicate_names:
        raise Exception(
            "レイヤ名またはレイヤグループ名が重複しています: {0}".format(
                ", ".join(sorted(set(duplicate_names), key=str.casefold))
            )
        )

    if output_path and not output_path.lower().endswith(".gpkg"):
        output_path += ".gpkg"

    project = QgsProject.instance()
    transform_context = project.transformContext()
    uri = _csv_uri(csv_path, x_field, y_field, crs)
    created_layers = []
    first_saved_layer = True
    root = project.layerTreeRoot()
    current_group = None
    groups_by_level = {}

    for index, config in enumerate(layer_configs):
        if config.get('type') == 'group':
            group_name = config.get('name') or 'group_{0}'.format(index + 1)
            if config.get('enabled', True) and add_to_project:
                level = int(config.get('level') or 1)
                if level <= 1:
                    current_group = get_or_create_group(root, group_name)
                    level = 1
                else:
                    parent_group = groups_by_level.get(level - 1)
                    if parent_group is None:
                        current_group = get_or_create_group(root, group_name)
                        level = 1
                    else:
                        current_group = parent_group.findGroup(group_name) or parent_group.addGroup(group_name)
                groups_by_level[level] = current_group
                for existing_level in list(groups_by_level):
                    if existing_level > level:
                        del groups_by_level[existing_level]
                created_layers.append('[Group] {0}'.format(group_name))
            else:
                current_group = None
                groups_by_level = {}
            continue

        layer_name = config.get('name') or 'layer_{0}'.format(index + 1)
        layer = QgsVectorLayer(uri, layer_name, "delimitedtext")
        if not layer.isValid():
            raise Exception("レイヤを作成できませんでした: {0}".format(layer_name))

        subset = build_layer_subset_expression(config.get('condition'))
        if subset:
            layer.setSubsetString(subset)

        symbol_color = config.get('symbol_color') or config.get('color') or '0,112,255,255'
        apply_symbol(
            layer,
            config.get('shape') or 'circle',
            symbol_color,
            float(config.get('size_mm') or 2.0),
        )
        label_size_mm = float(config.get('label_size_mm') or 3.0)
        label_text_color = config.get('label_text_color') or '0,0,0,255'
        label_background_color = config.get('label_background_color') or config.get('color') or symbol_color
        label_expression = config.get('label_expression') or ''
        label_background_transparency = config.get('label_background_transparency')
        if label_background_transparency is None:
            label_background_transparency = 80
        apply_configured_label(
            layer,
            config.get('label_field') or config.get('label'),
            label_background_color,
            label_size_mm,
            label_expression,
            label_background_transparency,
            label_text_color,
        )

        if output_path:
            _write_layer_to_gpkg(layer, output_path, layer_name, transform_context, first_saved_layer, output_crs or crs)
            first_saved_layer = False
            saved_uri = "{0}|layername={1}".format(output_path, layer_name)
            saved_layer = QgsVectorLayer(saved_uri, layer_name, "ogr")
            if saved_layer.isValid():
                try:
                    saved_layer.setRenderer(layer.renderer().clone())
                except Exception:
                    pass
                apply_configured_label(
                    saved_layer,
                    config.get('label_field') or config.get('label'),
                    label_background_color,
                    label_size_mm,
                    label_expression,
                    label_background_transparency,
                    label_text_color,
                )
                if add_to_project:
                    if current_group is not None:
                        project.addMapLayer(saved_layer, False)
                        current_group.addLayer(saved_layer)
                    else:
                        project.addMapLayer(saved_layer)
                created_layers.append(saved_layer.name())
            else:
                created_layers.append(layer_name)
        else:
            if add_to_project:
                if current_group is not None:
                    project.addMapLayer(layer, False)
                    current_group.addLayer(layer)
                else:
                    project.addMapLayer(layer)
            created_layers.append(layer.name())

    if iface is not None:
        iface.mapCanvas().refreshAllLayers()
        iface.messageBar().pushSuccess(
            "レイヤセットを追加",
            "{0} レイヤを作成しました。".format(len(created_layers)),
        )
        QMessageBox.information(
            iface.mainWindow(),
            "レイヤセットを追加",
            "作成レイヤ:\n{0}".format("\n".join(created_layers)),
        )

    return {
        "csv_path": csv_path,
        "output_path": output_path,
        "created_layers": created_layers,
        "created_count": len(created_layers),
    }


def select_ward(parent):
    selected_ward, ok = QInputDialog.getItem(
        parent,
        "区の選択",
        "〇〇区を選んでください：",
        WARD_NAMES,
        0,
        False
    )
    if not ok:
        return None
    return selected_ward


def select_shape(parent):
    shapes = ["circle", "square", "triangle", "diamond", "cross"]
    shape, ok = QInputDialog.getItem(
        parent,
        "シンボル形状",
        "シンボルの形を選んでください：",
        shapes,
        0,
        False
    )
    if not ok:
        return None
    return shape


def select_size(parent):
    size_mm, ok = QInputDialog.getDouble(
        parent,
        "サイズ設定",
        "サイズ(mm)を入力してください：",
        2.0, 0.1, 50.0, 1
    )
    if not ok:
        return None
    return size_mm


def run_main(
    iface,
    parent=None,
    csv_path=None,
    selected_ward=None,
    shape=None,
    size_mm=None,
    group_selection='group1',
    area_filter=None,
):
    """
    Plugin からも Python Console からも呼べる共通入口
    """
    project = QgsProject.instance()
    if isinstance(group_selection, str):
        group_selections = [group_selection]
    else:
        group_selections = list(group_selection or ['group1'])
    unknown_selections = [
        selection
        for selection in group_selections
        if selection not in ('group1', 'group2', 'group3')
    ]
    if unknown_selections:
        print(f"不明なグループ選択です: {unknown_selections}")
        return None

    if parent is None and iface is not None:
        parent = iface.mainWindow()

    start_dir = get_project_start_dir(project)

    if not csv_path:
        csv_path = select_csv_path(parent, start_dir)
        if not csv_path:
            print("CSV選択をキャンセルしました。")
            return None

    if 'group3' in group_selections and not selected_ward:
        selected_ward = select_ward(parent)
        if not selected_ward:
            print("区選択をキャンセルしました。")
            return None

    if not shape:
        shape = select_shape(parent)
        if not shape:
            print("シンボル形状の選択をキャンセルしました。")
            return None

    if size_mm is None:
        size_mm = select_size(parent)
        if size_mm is None:
            print("サイズ入力をキャンセルしました。")
            return None

    area_filter_expression = build_total_floor_area_expression(area_filter)
    area_group_suffix = build_total_floor_area_group_suffix(area_filter)

    csv_path_uri = csv_path.replace("\\", "/")
    uri = (
        f"file:///{csv_path_uri}"
        "?delimiter=,"
        "&xField=世界_10進_X"
        "&yField=世界_10進_Y"
        "&crs=EPSG:4326"
    )

    root = project.layerTreeRoot()

    order1, created1 = [], []
    order2, created2 = [], []
    order3, created3 = [], []
    group1_name = "一般施設_賃借施設" + area_group_suffix
    group2_name = "複合化可能一般施設_賃借施設" + area_group_suffix
    group3_name = None

    if 'group1' in group_selections:
        group1 = get_or_create_group(root, group1_name)
        order1, created1 = create_five_layers_in_group(
            project=project,
            iface=iface,
            uri=uri,
            group=group1,
            shape=shape,
            size_mm=size_mm,
            extra_filter=area_filter_expression
        )

    if 'group2' in group_selections:
        group2 = get_or_create_group(root, group2_name)
        order2, created2 = create_five_layers_in_group(
            project=project,
            iface=iface,
            uri=uri,
            group=group2,
            shape=shape,
            size_mm=size_mm,
            extra_filter=combine_filter_parts(
                '"複合不可理由" = \'01複合化可能\'',
                area_filter_expression,
            )
        )

    if 'group3' in group_selections:
        # 選択区内は全部表示し、区外は指定キーワードと7用途施設を除外する
        ward_safe = selected_ward.replace("'", "''")
        inside_ward_filter = f'"所在地" LIKE \'%{ward_safe}%\''
        outside_ward_filter = f'NOT ("所在地" LIKE \'%{ward_safe}%\')'

        excluded_name_filter = build_name_not_contains_all_expression(
            "施設名称",
            EXCLUDED_OUTSIDE_WARD_NAME_KEYWORDS
        )

        seven_use_empty_filter = build_field_is_empty_expression("7用途施設")

        inside_or_outside_filtered = (
            f'(({inside_ward_filter}) OR '
            f'(({outside_ward_filter}) AND {excluded_name_filter} AND {seven_use_empty_filter}))'
        )

        group3_name = f"複合化可能一般施設_賃借施設_{selected_ward}以外で7用途施設または消防署を除外{area_group_suffix}"
        group3_extra_filter = (
            combine_filter_parts(
                '"複合不可理由" = \'01複合化可能\'',
                inside_or_outside_filtered,
                area_filter_expression,
            )
        )

        group3 = get_or_create_group(root, group3_name)
        order3, created3 = create_five_layers_in_group(
            project=project,
            iface=iface,
            uri=uri,
            group=group3,
            shape=shape,
            size_mm=size_mm,
            extra_filter=group3_extra_filter
        )

    iface.mapCanvas().refreshAllLayers()

    result_info = {
        "csv_path": csv_path,
        "selected_ward": selected_ward,
        "group_selection": group_selections,
        "area_filter": area_filter,
        "group1_name": group1_name,
        "group2_name": group2_name,
        "group3_name": group3_name,
        "created_count": len(created1) + len(created2) + len(created3),
        "order1": order1,
        "order2": order2,
        "order3": order3
    }

    print("作成完了")
    print(f"CSV: {csv_path}")
    if selected_ward:
        print(f"選択区: {selected_ward}")
        print("\n選択区の外で除外する施設名称キーワード:")
        for kw in EXCLUDED_OUTSIDE_WARD_NAME_KEYWORDS:
            print(f"  - {kw}")
        print("\n選択区の外で「7用途施設」に値がある施設も除外します。")

    for group_name, order in (
        (group1_name, order1),
        (group2_name, order2),
        (group3_name, order3),
    ):
        if group_name and order:
            print(f"\n{group_name} グループ内の表示順（上→下）:")
            for d in order:
                print(f"  - {d['name']}")

    print(f"\n作成レイヤ数: {result_info['created_count']}")

    return result_info
