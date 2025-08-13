from __future__ import annotations
import logging
import asyncio
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_HS_COLOR,
    ATTR_TRANSITION,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import async_track_state_change_event
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
    DEFAULT_MAX_BRIGHTNESS,
    DEFAULT_MIN_BRIGHTNESS,
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
    min_map: dict[str, int] = {e: int(src_min.get(e, DEFAULT_MIN_BRIGHTNESS)) for e in entities}
    max_map: dict[str, int] = {e: int(src_max.get(e, DEFAULT_MAX_BRIGHTNESS)) for e in entities}
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
    _attr_available = True
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
        # Matter/Alexa-Kompatibilität: Explizite Kategorisierung
        self._attr_entity_category = None  # Hauptgerät, nicht versteckt
        self.entities = [e for e in entities if isinstance(e, str) and e]
        self.factors = factors
        self.min_map = min_map
        self.max_map = max_map
        # gamma removed
        self.forward_ct = forward_ct
        self.forward_color = forward_color
        self._child_supports_ct: dict[str, bool] = {}
        self._child_supports_color: dict[str, bool] = {}
        
        # Initialisiere mit Standard-Farbmodus
        self._attr_color_mode = ColorMode.BRIGHTNESS
        self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
        
        self._refresh_child_capabilities()

        # Finale Capabilities einmalig festlegen (stabil für Matter-Kompatibilität)
        self._finalize_supported_color_modes()

        self._is_on = False
        self._master_brightness = DEFAULT_MAX_BRIGHTNESS
        self._last_kelvin: int | None = None
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

    @property
    def device_class(self) -> str:
        """Return device class for Matter/Alexa compatibility."""
        return "light"

    @callback
    def _subscribe_child_states(self):
        @callback
        def _state_changed(event):
            eid = event.data.get("entity_id")
            any_on = any(self.hass.states.is_state(e, "on") for e in self.entities)
            self._is_on = any_on
            # Nur den on/off Status aktualisieren, keine Capabilities neu berechnen
            # (Capabilities bleiben stabil für Matter-Kompatibilität)
            self.async_write_ha_state()
        # Spezifische State-Tracker für bessere Performance
        self._unsubs.append(async_track_state_change_event(self.hass, self.entities, _state_changed))

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Beim Hinzufügen einmal Fähigkeiten der Kinder erfassen und UI anpassen
        self._refresh_child_capabilities()
        self._finalize_supported_color_modes()
        if (state := await self.async_get_last_state()) is not None:
            self._is_on = state.state == "on"
            mb = state.attributes.get(ATTR_MASTER_BRIGHTNESS)
            if mb is not None:
                # Stelle sicher, dass der gespeicherte Wert im Matter-Bereich liegt
                self._master_brightness = max(DEFAULT_MIN_BRIGHTNESS, min(DEFAULT_MAX_BRIGHTNESS, int(mb)))
            # Prefer Kelvin; fallback von Mireds
            last_kelvin = state.attributes.get("color_temp_kelvin")
            if last_kelvin is None:
                last_mireds = state.attributes.get("color_temp")
                if last_mireds is not None:
                    try:
                        last_kelvin = int(round(1000000.0 / float(last_mireds)))
                    except Exception:
                        last_kelvin = None
            if last_kelvin is not None:
                self._last_kelvin = int(last_kelvin)
            self._last_hs = state.attributes.get(ATTR_HS_COLOR)
            # Farbmodus entsprechend letztem Zustand wählen, falls erlaubt
            if self.forward_color and self._last_hs is not None:
                self._set_color_mode_if_supported(ColorMode.HS)
            elif self.forward_ct and self._last_kelvin is not None:
                self._set_color_mode_if_supported(ColorMode.COLOR_TEMP)
        # Initialen Zustand veröffentlichen
        self.async_write_ha_state()

    # ---------- LightEntity API ----------
    @property
    def is_on(self) -> bool:
        return self._is_on

    @property
    def brightness(self) -> int | None:
        # Matter-kompatibel: Bei ausgeschaltetem Zustand None zurückgeben
        # Bei eingeschaltetem Zustand den Wert im Matter-Bereich 1-254
        if not self._is_on:
            return None
        return self._master_brightness

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        # `entity_id` sorgt dafür, dass die Frontend-Detailansicht (More Info)
        # die Mitglieder wie bei einer normalen Lichtgruppe mit anzeigt.
        return {
            "entity_id": list(self.entities),
            ATTR_MASTER_BRIGHTNESS: self._master_brightness,
            ATTR_FACTORS: self.factors,
            ATTR_MIN: self.min_map,
            ATTR_MAX: self.max_map,
        }

    @property
    def hs_color(self) -> tuple[float, float] | None:
        # Aktuellen Farbwert zurückgeben, damit UI den Farbwähler initialisiert
        if self.forward_color and self._is_on:
            return self._last_hs
        return None

    @property
    def color_temp_kelvin(self) -> int | None:
        # Aktuelle Kelvin-Farbtemperatur zurückgeben
        if self.forward_ct and self._is_on:
            return self._last_kelvin
        return None

    async def async_turn_on(self, **kwargs: Any) -> None:
        # Brightness im Matter-kompatiblen Bereich 0-254 begrenzen
        b = int(kwargs.get(ATTR_BRIGHTNESS, self._master_brightness))
        self._master_brightness = max(DEFAULT_MIN_BRIGHTNESS, min(DEFAULT_MAX_BRIGHTNESS, int(b)))
        
        # Farbtemperatur (Kelvin bevorzugt; Mireds kompatibel) akzeptieren
        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            try:
                kelvin = float(kwargs.get(ATTR_COLOR_TEMP_KELVIN))
                if kelvin > 0:
                    self._last_kelvin = int(round(kelvin))
                    if self.forward_ct:
                        self._set_color_mode_if_supported(ColorMode.COLOR_TEMP)
            except Exception:
                pass
        elif "color_temp" in kwargs:
            try:
                mireds = float(kwargs.get("color_temp"))
                if mireds > 0:
                    self._last_kelvin = int(round(1000000.0 / mireds))
                    if self.forward_ct:
                        self._set_color_mode_if_supported(ColorMode.COLOR_TEMP)
            except Exception:
                pass
        if ATTR_HS_COLOR in kwargs:
            self._last_hs = tuple(kwargs[ATTR_HS_COLOR])  # type: ignore[assignment]
            if self.forward_color:
                self._set_color_mode_if_supported(ColorMode.HS)
        tr = kwargs.get(ATTR_TRANSITION)
        # Optimistic state update für Matter-Kompatibilität
        self._is_on = True
        self.async_write_ha_state()
        await self.async_apply_to_children(transition=tr)

    async def async_turn_off(self, **kwargs: Any) -> None:
        data = {}
        if ATTR_TRANSITION in kwargs:
            data[ATTR_TRANSITION] = kwargs[ATTR_TRANSITION]
        self._is_on = False
        self.async_write_ha_state()
        await self.hass.services.async_call("light", "turn_off", {"entity_id": self.entities, **data}, blocking=False)

    # ---------- Helpers ----------
    def _apply_gamma(self, base: int) -> int:
        # gamma removed: passthrough
        return base

    async def async_apply_to_children(self, transition: float | None = None) -> None:
        base = self._apply_gamma(self._master_brightness)
        tasks = []
        for eid in self.entities:
            fac = float(self.factors.get(eid, 1.0))
            target = int(round(base * fac))
            target = max(self.min_map.get(eid, DEFAULT_MIN_BRIGHTNESS),
                        min(self.max_map.get(eid, DEFAULT_MAX_BRIGHTNESS), target))

            payload: dict[str, Any] = {ATTR_BRIGHTNESS: target}
            if transition is not None:
                payload[ATTR_TRANSITION] = transition
            if self.forward_ct and self._last_kelvin is not None and self._child_supports_ct.get(eid, False):
                payload[ATTR_COLOR_TEMP_KELVIN] = self._last_kelvin
            if self.forward_color and self._last_hs is not None and self._child_supports_color.get(eid, False):
                payload[ATTR_HS_COLOR] = self._last_hs

            # WICHTIG: coroutine sammeln
            tasks.append(
                self.hass.services.async_call("light", "turn_on", {"entity_id": eid, **payload}, blocking=False)
            )
        if tasks:
            # führt die coroutines tatsächlich aus; wartet NICHT auf Gerätezustellungsende
            await asyncio.gather(*tasks, return_exceptions=True)



    # ---------- Capabilities ----------
    def _refresh_child_capabilities(self, only_entities: list[str] | None = None) -> None:
        target_list = only_entities if only_entities is not None else self.entities
        min_k_values: list[int] = []
        max_k_values: list[int] = []
        for child in target_list:
            st = self.hass.states.get(child)
            supports_ct = False
            supports_color = False
            if st is not None:
                scm = st.attributes.get("supported_color_modes")
                if isinstance(scm, (list, set)):
                    modes = {str(m).lower() for m in scm}
                    # Farbtemperatur
                    supports_ct = "color_temp" in modes
                    # Farbe (beliebiger Farbraum)
                    color_modes = {"hs", "xy", "rgb", "rgbw", "rgbww", "rgbcw"}
                    supports_color = any(m in modes for m in color_modes)
                # Kelvin-Bereich ermitteln
                if supports_ct:
                    child_min_k = st.attributes.get("min_color_temp_kelvin")
                    child_max_k = st.attributes.get("max_color_temp_kelvin")
                    if child_min_k is None or child_max_k is None:
                        # Fallback über mireds
                        min_mireds = st.attributes.get("min_mireds")
                        max_mireds = st.attributes.get("max_mireds")
                        if max_mireds is not None:
                            try:
                                child_min_k = int(round(1000000.0 / float(max_mireds)))
                            except Exception:
                                child_min_k = None
                        if min_mireds is not None:
                            try:
                                child_max_k = int(round(1000000.0 / float(min_mireds)))
                            except Exception:
                                child_max_k = None
                    if isinstance(child_min_k, (int, float)):
                        min_k_values.append(int(child_min_k))
                    if isinstance(child_max_k, (int, float)):
                        max_k_values.append(int(child_max_k))
            self._child_supports_ct[child] = supports_ct
            self._child_supports_color[child] = supports_color
        # Gruppen-Kelvin-Bereich als Schnittmenge der Kinder (nur beim ersten Mal setzen)
        if not hasattr(self, '_attr_min_color_temp_kelvin') and min_k_values and max_k_values:
            self._attr_min_color_temp_kelvin = max(min_k_values)
            self._attr_max_color_temp_kelvin = min(max_k_values)
            if self._attr_min_color_temp_kelvin > self._attr_max_color_temp_kelvin:
                # Fallback: unrealistischer Schnitt – nimm Spanne des ersten Kindes
                self._attr_min_color_temp_kelvin = min(min_k_values)
                self._attr_max_color_temp_kelvin = max(max_k_values)
        elif not hasattr(self, '_attr_min_color_temp_kelvin'):
            self._attr_min_color_temp_kelvin = None
            self._attr_max_color_temp_kelvin = None

    # ---------- Modes ----------
    def _finalize_supported_color_modes(self) -> None:
        """Finale Capabilities einmalig festlegen (stabil für Matter-Kompatibilität)
        
        WICHTIG: Diese Methode wird nur einmal bei der Initialisierung aufgerufen.
        Matter/Alexa benötigen stabile Geräteeigenschaften und reagieren schlecht
        auf dynamische Änderungen der supported_color_modes.
        """
        modes: set[ColorMode] = {ColorMode.BRIGHTNESS}  # BRIGHTNESS immer unterstützt
        
        has_ct = self.forward_ct and any(self._child_supports_ct.values())
        has_color = self.forward_color and any(self._child_supports_color.values())
        
        if has_color:
            modes.add(ColorMode.HS)
        if has_ct:
            modes.add(ColorMode.COLOR_TEMP)
            
        self._attr_supported_color_modes = modes
        
        # Stelle sicher, dass der aktuelle Farbmodus ein gültiger ist
        if self._attr_color_mode not in modes:
            self._attr_color_mode = ColorMode.BRIGHTNESS

    def _recompute_supported_color_modes(self) -> None:
        """Legacy-Methode - ENTFERNT für stabile Matter-Kompatibilität
        
        Diese Methode wurde entfernt, da dynamische Änderungen der supported_color_modes
        zu Problemen mit Matter/Alexa führen. Die Farbmodi werden einmalig bei der
        Initialisierung durch _finalize_supported_color_modes() festgelegt.
        """
        # Absichtlich leer - keine dynamischen Änderungen mehr
        pass

    def _set_color_mode_if_supported(self, preferred: ColorMode) -> None:
        modes = self._attr_supported_color_modes or {ColorMode.BRIGHTNESS}
        if preferred in modes:
            self._attr_color_mode = preferred
            return
        if ColorMode.HS in modes:
            self._attr_color_mode = ColorMode.HS
        elif ColorMode.COLOR_TEMP in modes:
            self._attr_color_mode = ColorMode.COLOR_TEMP
        else:
            self._attr_color_mode = ColorMode.BRIGHTNESS

    def set_factor(self, child: str, factor: float) -> None:
        self.factors[child] = float(factor)

    def set_min_max(self, child: str, min_v: int, max_v: int) -> None:
        # Stelle sicher, dass die Min/Max-Werte im Matter-kompatiblen Bereich liegen
        self.min_map[child] = max(DEFAULT_MIN_BRIGHTNESS, int(min_v))
        self.max_map[child] = max(DEFAULT_MIN_BRIGHTNESS, min(DEFAULT_MAX_BRIGHTNESS, int(max_v)))

    async def async_write_parameters(self):
        # just update state; parameters live in memory (options flow updates config)
        self.async_write_ha_state()