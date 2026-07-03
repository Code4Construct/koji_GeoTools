# Koji GeoTools

Koji GeoTools is a QGIS plugin that provides a single launcher for frequently
used vector geoprocessing workflows.

It includes tools for creating project layer sets, building study areas from
boundaries and buffers, and extracting visible point or polygon features inside
selected polygons.

## Features

- `add_sets_layers`: create layer sets from CSV data for facility planning maps.
- `study_area_builder`: create study area outputs from selected features or map coordinates.
- `merge_features_in_polygon`: extract visible point and polygon features inside a selected polygon.

## Configuration

The plugin does not ship with bundled preset files.

When the launcher is opened, Koji GeoTools creates a project-side configuration
folder next to the current QGIS project file. Tool settings are saved there as
`preset.json` files.

Example:

```text
sample.qgz
sample_KGT/
  レイヤセットを保存/
    preset.json
  調査エリア設定/
    preset.json
  ポリゴン内の地物抽出/
    preset.json
```

## Usage

1. Enable `Koji GeoTools` in the QGIS plugin manager.
2. Open `Koji GeoTools` from the toolbar or plugin menu.
3. Select the workflow you want to run.
4. Update presets from each tool when project-specific settings are needed.

## 日本語

Koji GeoTools は、`kojiGIS4QGIS` から利用頻度の高いベクター処理をまとめた
QGIS プラグインです。

1つのランチャーから、レイヤセット作成、調査エリア設定、ポリゴン内の
地物抽出を起動できます。

設定ファイルはプラグイン内に同梱せず、QGISプロジェクトファイルの横に作成
される `_KGT` フォルダへ保存します。
