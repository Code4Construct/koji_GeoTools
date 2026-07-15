# Koji GeoTools

Koji GeoTools is a QGIS plugin that provides a single launcher for frequently
used vector geoprocessing workflows.

It includes tools for creating project layer sets, building study areas from
selected features or map coordinates, and extracting visible point or polygon
features inside selected polygons.

## Features

- `add_sets_layers`: create layer sets from CSV data for facility-planning maps.
- `study_area_builder`: create study-area outputs from selected features or map coordinates.
- `merge_features_in_polygon`: extract visible point and polygon features inside a selected polygon.

## Configuration

The plugin does not ship with bundled preset files.

When the launcher is opened, Koji GeoTools creates a project-side configuration
folder next to the current QGIS project file. Tool settings are saved there as
`preset.json` files.

Example:

```text
sample.qgz
sample_KGTconfig/
  layer_sets/
    preset.json
  study_area/
    preset.json
  polygon_feature_extraction/
    preset.json
```

## Usage

1. Enable `Koji GeoTools` in the QGIS plugin manager.
2. Open `Koji GeoTools` from the toolbar or plugin menu.
3. Select the workflow you want to run.
4. Update presets from each tool when project-specific settings are needed.

## Documentation

Project documentation and download information are available at:

https://www.arinobu.org/koji_geotools.html
