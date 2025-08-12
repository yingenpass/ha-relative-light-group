from __future__ import annotations
import logging
import asyncio
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP,
    ATTR_HS_COLOR,
    ATTR_TRANSITION,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.const import CONF_NAME

from .const import (
    DOMAIN,
    CONF_ENTITIES,
    CONF_FACTORS,
    CONF_MIN,
    CONF_MAX,
    CONF_FORWARD_CT,
    CONF_FORWARD_COLOR,
    DEFAULT_NAME,
    ATTR_MASTER_BRIGHTNESS,
    ATTR_FACTORS,
    ATTR_MIN,
    ATTR_MAX,
    SERVICE_SET_FACTOR,
    SERVICE_SET_MIN_MAX,
    SERVICE_APPLY,
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities):
    data = {**entry.data, **entry.options}
    name = data.get(CONF_NAME, DEFAULT_NAME)
    def _normalize_entities(value) -> list[str]:
        if isinstance(value, str):
            return [value]
        result: list[str] = []
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item:
                    result.append(item)
                elif isinstance(item, dict):
                    cand = item.get("entity_id") or item.get("entity")
                    if isinstance(cand, str) and cand:
                        result.append(cand)
        return result

    entities = _normalize_entities(data.get(CONF_ENTITIES, []))

    src_factors = data.get(CONF_FACTORS, {})
    if not isinstance(src_factors, dict):
        src_factors = {}
    src_min = data.get(CONF_MIN, {})
    if not isinstance(src_min, dict):
        src_min = {}
    src_max = data.get(CONF_MAX, {})
    if not isinstance(src_max, dict):
        src_max = {}

    factors: dict[str, float] = {e: float(src_factors.get(e, 1.0)) for e in entities}
    min_map: dict[str, int] = {e: int(src_min.get(e, 1)) for e in entities}
    max_map: dict[str, int] = {e: int(src_max.get(e, 255)) for e in entities}
    forward_ct = bool(data.get(CONF_FORWARD_CT, False))
    forward_color = bool(data.get(CONF_FORWARD_COLOR, False))

    rel = RelativeLightGroup(
        hass,
        name,
        entities,
        factors,
        min_map,
        max_map,
        forward_ct,
        forward_color,
        unique_id=entry.entry_id,
    )

    async_add_entities([rel])

class RelativeLightGroup(LightEntity, RestoreEntity):
    _attr_should_poll = False
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_available = True
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_features = LightEntityFeature.TRANSITION

    def __init__(
        self,
        hass: HomeAssistant,
        name: str,
        entities: list[str],
        factors: dict[str, float],
        min_map: dict[str, int],
        max_map: dict[str, int],
        forward_ct: bool,
        forward_color: bool,
        unique_id: str | None = None,
    ) -> None:
        self.hass = hass
        self._attr_name = name
        self._attr_unique_id = unique_id
        self.entities = [e for e in entities if isinstance(e, str) and e]
        self.factors = factors
        self.min_map = min_map
        self.max_map = max_map
        # gamma removed
        self.forward_ct = forward_ct
        self.forward_color = forward_color

        self._is_on = False
        self._master_brightness = 255
        self._last_ct: int | None = None
        self._last_hs: tuple[float, float] | None = None

        # listen only to on/off availability changes to reflect is_on; do not read brightness back
        self._unsubs: list[Any] = []
        self._subscribe_child_states()
        # mark unavailable if no children configured
        if not self.entities:
            self._attr_available = False

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self.unique_id or self.name)}, name=self.name)

    @callback
    def _subscribe_child_states(self):
        @callback
        def _state_changed(event):
            eid = event.data.get("entity_id")
            if eid not in self.entities:
                return
            any_on = any(self.hass.states.is_state(e, "on") for e in self.entities)
            self._is_on = any_on
            self.async_write_ha_state()
        self._unsubs.append(self.hass.bus.async_listen("state_changed", _state_changed))

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (state := await self.async_get_last_state()) is not None:
            self._is_on = state.state == "on"
            mb = state.attributes.get(ATTR_MASTER_BRIGHTNESS)
            if mb is not None:
                self._master_brightness = int(mb)
            self._last_ct = state.attributes.get(ATTR_COLOR_TEMP)
            self._last_hs = state.attributes.get(ATTR_HS_COLOR)

    # ---------- LightEntity API ----------
    @property
    def is_on(self) -> bool:
        return self._is_on

    @property
    def brightness(self) -> int | None:
        return self._master_brightness if self._is_on else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            ATTR_MASTER_BRIGHTNESS: self._master_brightness,
            ATTR_FACTORS: self.factors,
            ATTR_MIN: self.min_map,
            ATTR_MAX: self.max_map,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        b = int(kwargs.get(ATTR_BRIGHTNESS, self._master_brightness))
        self._master_brightness = max(1, min(255, int(b)))
        if ATTR_COLOR_TEMP in kwargs:
            self._last_ct = int(kwargs[ATTR_COLOR_TEMP])
        if ATTR_HS_COLOR in kwargs:
            self._last_hs = tuple(kwargs[ATTR_HS_COLOR])  # type: ignore[assignment]
        tr = kwargs.get(ATTR_TRANSITION)
        await self.async_apply_to_children(transition=tr)
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        data = {}
        if ATTR_TRANSITION in kwargs:
            data[ATTR_TRANSITION] = kwargs[ATTR_TRANSITION]
        await self.hass.services.async_call("light", "turn_off", {"entity_id": self.entities, **data}, blocking=False)
        self._is_on = False
        self.async_write_ha_state()

    # ---------- Helpers ----------
    def _apply_gamma(self, base: int) -> int:
        # gamma removed: passthrough
        return base

    async def async_apply_to_children(self, transition: float | None = None) -> None:
        base255 = self._apply_gamma(self._master_brightness)
        tasks = []
        for eid in self.entities:
            fac = float(self.factors.get(eid, 1.0))
            target = int(round(base255 * fac))
            target = max(self.min_map.get(eid, 1), min(self.max_map.get(eid, 255), target))
            payload: dict[str, Any] = {ATTR_BRIGHTNESS: target}
            if transition is not None:
                payload[ATTR_TRANSITION] = transition
            if self.forward_ct and self._last_ct is not None:
                payload[ATTR_COLOR_TEMP] = self._last_ct
            if self.forward_color and self._last_hs is not None:
                payload[ATTR_HS_COLOR] = self._last_hs
            tasks.append(self.hass.services.async_call("light", "turn_on", {"entity_id": eid, **payload}, blocking=True))
        if tasks:
            await asyncio.gather(*tasks)

    def set_factor(self, child: str, factor: float) -> None:
        self.factors[child] = float(factor)

    def set_min_max(self, child: str, min_v: int, max_v: int) -> None:
        self.min_map[child] = int(min_v)
        self.max_map[child] = int(max_v)

    async def async_write_parameters(self):
        # just update state; parameters live in memory (options flow updates config)
        self.async_write_ha_state()