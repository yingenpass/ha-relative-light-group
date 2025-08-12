from __future__ import annotations
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import CONF_NAME
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    CONF_ENTITIES,
    CONF_FACTORS,
    CONF_MIN,
    CONF_MAX,
    CONF_FORWARD_CT,
    CONF_FORWARD_COLOR,
    DEFAULT_NAME,
)

STEP_USER = vol.Schema({
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
    vol.Required(CONF_ENTITIES): selector.selector({
        "entity": {"multiple": True, "reorder": True, "domain": "light"}
    }),
    vol.Optional(CONF_FORWARD_CT, default=False): bool,
    vol.Optional(CONF_FORWARD_COLOR, default=False): bool,
})


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._user_data: dict | None = None
        self._members_keymap: dict[str, tuple[str, str]] = {}
    
    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OptionsFlowHandler(config_entry)

    # Options-Flow wird via Modul-Funktion am Ende bereitgestellt

    async def async_step_user(self, user_input=None):
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=STEP_USER)
        # Store selection and continue to per-member configuration
        self._user_data = dict(user_input)
        # normalize entities to list[str]
        self._user_data[CONF_ENTITIES] = _normalize_entities(self._user_data.get(CONF_ENTITIES, []))
        return await self.async_step_members()

    async def async_step_members(self, user_input=None):
        assert self._user_data is not None
        entities = list(self._user_data.get(CONF_ENTITIES, []))
        # Dynamic schema per child with friendly labels
        schema: dict = {}
        self._members_keymap = {}
        for e in entities:
            friendly = self._friendly_name(e)
            k_factor = f"Faktor – {friendly}"
            k_min = f"Minimum – {friendly}"
            k_max = f"Maximum – {friendly}"
            schema[vol.Optional(k_factor, default=1.0)] = selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=5, step=0.01, mode=selector.NumberSelectorMode.BOX)
            )
            schema[vol.Optional(k_min, default=1)] = int
            schema[vol.Optional(k_max, default=255)] = int
            self._members_keymap[k_factor] = ("factor", e)
            self._members_keymap[k_min] = ("min", e)
            self._members_keymap[k_max] = ("max", e)

        if user_input is None:
            return self.async_show_form(step_id="members", data_schema=vol.Schema(schema))

        # Merge and create entry
        data = dict(self._user_data)
        data[CONF_FACTORS] = {}
        data[CONF_MIN] = {}
        data[CONF_MAX] = {}
        for label, (kind, eid) in self._members_keymap.items():
            if kind == "factor":
                data[CONF_FACTORS][eid] = float(user_input.get(label, 1.0))
            elif kind == "min":
                data[CONF_MIN][eid] = int(user_input.get(label, 1))
            elif kind == "max":
                data[CONF_MAX][eid] = int(user_input.get(label, 255))

        return self.async_create_entry(title=data.get(CONF_NAME, DEFAULT_NAME), data=data)

    async def async_step_import(self, user_input):
        # not used, but allows YAML import in future
        return await self.async_step_user(user_input)


class OptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry):
        self.config_entry = config_entry
        self._draft_globals: dict | None = None
        self._members_keymap: dict[str, tuple[str, str]] = {}

    async def async_step_init(self, user_input=None):
        return await self.async_step_edit()

    async def async_step_edit(self, user_input=None):
        data = self._merged()
        entities = _normalize_entities(data.get(CONF_ENTITIES, []))
        schema = {
            vol.Optional(CONF_NAME, default=data.get(CONF_NAME, DEFAULT_NAME)): str,
            vol.Optional(CONF_ENTITIES, default=entities): selector.selector({
                "entity": {"multiple": True, "reorder": True, "domain": "light"}
            }),
            vol.Optional(CONF_FORWARD_CT, default=data.get(CONF_FORWARD_CT, False)): bool,
            vol.Optional(CONF_FORWARD_COLOR, default=data.get(CONF_FORWARD_COLOR, False)): bool,
        }

        if user_input is None:
            return self.async_show_form(step_id="edit", data_schema=vol.Schema(schema))

        # Store globals and go to per-member edit
        new_entities = _normalize_entities(user_input.get(CONF_ENTITIES, entities))
        self._draft_globals = {
            CONF_NAME: user_input.get(CONF_NAME, data.get(CONF_NAME, DEFAULT_NAME)),
            CONF_ENTITIES: new_entities,
            CONF_FORWARD_CT: bool(user_input.get(CONF_FORWARD_CT, data.get(CONF_FORWARD_CT, False))),
            CONF_FORWARD_COLOR: bool(user_input.get(CONF_FORWARD_COLOR, data.get(CONF_FORWARD_COLOR, False))),
        }
        return await self.async_step_edit_members()

    async def async_step_edit_members(self, user_input=None):
        data = self._merged()
        draft = self._draft_globals or {}
        entities = _normalize_entities(draft.get(CONF_ENTITIES, data.get(CONF_ENTITIES, [])))

        # Dynamic per-child schema with friendly labels
        schema: dict = {}
        self._members_keymap = {}
        for e in entities:
            friendly = self._friendly_name(e)
            k_factor = f"Faktor – {friendly}"
            k_min = f"Minimum – {friendly}"
            k_max = f"Maximum – {friendly}"
            schema[vol.Optional(
                k_factor,
                default=float(data.get(CONF_FACTORS, {}).get(e, 1.0)),
            )] = selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=5, step=0.01, mode=selector.NumberSelectorMode.BOX)
            )
            schema[vol.Optional(k_min, default=int(data.get(CONF_MIN, {}).get(e, 1)))] = int
            schema[vol.Optional(k_max, default=int(data.get(CONF_MAX, {}).get(e, 255)))] = int
            self._members_keymap[k_factor] = ("factor", e)
            self._members_keymap[k_min] = ("min", e)
            self._members_keymap[k_max] = ("max", e)

        if user_input is None:
            return self.async_show_form(step_id="edit_members", data_schema=vol.Schema(schema))

        # Build final options
        opts = {
            CONF_NAME: draft.get(CONF_NAME, data.get(CONF_NAME, DEFAULT_NAME)),
            CONF_FORWARD_CT: bool(draft.get(CONF_FORWARD_CT, data.get(CONF_FORWARD_CT, False))),
            CONF_FORWARD_COLOR: bool(draft.get(CONF_FORWARD_COLOR, data.get(CONF_FORWARD_COLOR, False))),
            CONF_ENTITIES: entities,
            CONF_FACTORS: {},
            CONF_MIN: {},
            CONF_MAX: {},
        }
        for label, (kind, eid) in self._members_keymap.items():
            if kind == "factor":
                opts[CONF_FACTORS][eid] = float(user_input.get(label, float(data.get(CONF_FACTORS, {}).get(eid, 1.0))))
            elif kind == "min":
                opts[CONF_MIN][eid] = int(user_input.get(label, int(data.get(CONF_MIN, {}).get(eid, 1))))
            elif kind == "max":
                opts[CONF_MAX][eid] = int(user_input.get(label, int(data.get(CONF_MAX, {}).get(eid, 255))))

        return self.async_create_entry(title="Options", data=opts)

    def _merged(self):
        return self.config_entry.data | self.config_entry.options

    def _friendly_name(self, eid: str) -> str:
        st = self.hass.states.get(eid)
        if st and st.name:
            return st.name
        try:
            return eid.split(".", 1)[1].replace("_", " ").title()
        except Exception:
            return eid

def async_get_options_flow(config_entry):
    return OptionsFlowHandler(config_entry)


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
