from __future__ import annotations
DOMAIN = "relative_light_group"
PLATFORMS = ["light"]

CONF_ENTITIES = "entities"
CONF_FACTORS = "factors"
CONF_MIN = "min"
CONF_MAX = "max"
CONF_NAME = "name"
CONF_FORWARD_CT = "forward_color_temp"
CONF_FORWARD_COLOR = "forward_color"

DEFAULT_NAME = "Relative Light Group"

# Matter-kompatible Standardwerte
# Matter LevelControl: 0-254 (255 ist reserviert)
# Mindestwert 1, da 0 von einigen Stacks als "off/invalid" interpretiert wird
DEFAULT_MAX_BRIGHTNESS = 254
DEFAULT_MIN_BRIGHTNESS = 1

ATTR_MASTER_BRIGHTNESS = "master_brightness"
ATTR_FACTORS = "factors"
ATTR_MIN = "min"
ATTR_MAX = "max"

SERVICE_SET_FACTOR = "set_factor"
SERVICE_SET_MIN_MAX = "set_min_max"
SERVICE_APPLY = "apply"  # reapplies current master to children