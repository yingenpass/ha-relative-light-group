# Relative Light Group (Home Assistant)

A light entity that controls multiple child lights with **relative brightness factors** and **no feedback normalization**.

## Features
- Relative brightness via per-child **factor** (e.g. 1.0 : 0.7 : 1.3)
- Per-child **min/max** clamps (1–254 for Matter compatibility)
- Global **gamma** for perceived dimming
- Pass-through **transition**; optional pass-through of **color temperature** and **color**
- **Config Flow / Options Flow** (no YAML required)
- **Restore state** for master brightness
- Runtime services: `relative_light_group.set_factor`, `set_min_max`, `set_gamma`, `apply`
- **Matter Hub compatible** - Optimized for Alexa, Google Home, and other Matter controllers

## Matter Compatibility
This integration is specifically optimized for Home Assistant's Matter Hub Add-On:

### 🔧 **Key Improvements:**
- **Stable Capabilities**: `supported_color_modes` remain constant during operation
- **Optimistic State Updates**: State changes are published immediately for responsive controllers
- **Matter-Compliant Brightness**: Uses 1-254 range (0 reserved, 255 causes bridge errors)
- **Consistent State Reporting**: Always returns brightness value, even when off
- **Stable Kelvin Ranges**: Color temperature limits are set once and remain constant
- **Non-blocking Operations**: Faster response times with async service calls

### 🎯 **Solves Common Matter Issues:**
- ❌ "Ein Problem ist aufgetreten" in Alexa
- ❌ No live updates from controllers
- ❌ Inconsistent device capabilities
- ❌ Brightness values outside Matter specifications

## Installation
1. Copy `custom_components/relative_light_group` into your Home Assistant `config/custom_components/` folder.
2. Restart Home Assistant.
3. Go to *Settings → Devices & services → Add Integration* and search for **Relative Light Group**.
4. Pick your member lights. Adjust options in the integration's *Configure* dialog.

## Services
- `relative_light_group.set_factor` – Set a child's factor
- `relative_light_group.set_min_max` – Set a child's min/max (1–254)
- `relative_light_group.set_gamma` – Set the group's gamma
- `relative_light_group.apply` – Re-apply current master to all children

## Notes
- The entity **does not read** child brightness back; only on/off availability is observed to reflect the overall state.
- Scenes target the master as a single light; the group will fan out commands with your factors.
- **Matter Integration**: Works seamlessly with Alexa, Google Home, and other Matter controllers through the Matter Hub.
- **Performance**: Uses optimized state tracking for better responsiveness.

## Optional YAML (advanced)
```yaml
relative_light_group:
```
(Only UI is supported by default; YAML import can be added through `async_step_import`.)

## Example Automations
- Use standard `light.turn_on` with `brightness`/`transition` on the group.
- Use the `apply` service to re-sync after manual changes to children (if you ever do that).