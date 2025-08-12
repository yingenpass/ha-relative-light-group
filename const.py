from __future__ import annotations
DOMAIN = "relative_light_group"
PLATFORMS = ["light"]

CONF_ENTITIES = "entities"
CONF_FACTORS = "factors"
CONF_MIN = "min"
CONF_MAX = "max"
CONF_GAMMA = "gamma"
CONF_NAME = "name"
CONF_FORWARD_CT = "forward_color_temp"
CONF_FORWARD_COLOR = "forward_color"

DEFAULT_GAMMA = 1.0
DEFAULT_NAME = "Relative Light Group"

ATTR_MASTER_BRIGHTNESS = "master_brightness"
ATTR_FACTORS = "factors"
ATTR_MIN = "min"
ATTR_MAX = "max"

SERVICE_SET_FACTOR = "set_factor"
SERVICE_SET_MIN_MAX = "set_min_max"
SERVICE_SET_GAMMA = "set_gamma"
SERVICE_APPLY = "apply"  # reapplies current master to children