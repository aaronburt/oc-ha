"""AI Task support for OpenCode."""

import logging
from json import JSONDecodeError
from typing import override

from homeassistant.components import ai_task, conversation
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.json import json_loads

from . import OpenCodeConfigEntry
from .entity import OpenCodeBaseLLMEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

AI_TASK_ITERATIONS = 1000


async def async_setup_entry(
    hass,
    config_entry: OpenCodeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up AI Task entities."""
    for subentry in config_entry.subentries.values():
        if subentry.subentry_type != "ai_task_data":
            continue
        async_add_entities(
            [OpenCodeAITaskEntity(config_entry, subentry)],
            config_subentry_id=subentry.subentry_id,
        )


class OpenCodeAITaskEntity(ai_task.AITaskEntity, OpenCodeBaseLLMEntity):
    """OpenCode AI Task entity."""

    def __init__(self, entry: OpenCodeConfigEntry, subentry) -> None:
        """Initialize the entity."""
        super().__init__(entry, subentry)
        self._attr_supported_features = ai_task.AITaskEntityFeature.GENERATE_DATA

    @override
    async def _async_generate_data(
        self,
        task: ai_task.GenDataTask,
        chat_log: conversation.ChatLog,
    ) -> ai_task.GenDataTaskResult:
        """Handle a generate data task."""
        await self._async_handle_chat_log(
            chat_log,
            structure=task.structure,
            structure_name=task.name,
            max_iterations=AI_TASK_ITERATIONS,
        )

        if not chat_log.content or not isinstance(
            chat_log.content[-1], conversation.AssistantContent
        ):
            raise HomeAssistantError("OpenCode returned no assistant response")

        text = chat_log.content[-1].content or ""

        if not task.structure:
            return ai_task.GenDataTaskResult(
                conversation_id=chat_log.conversation_id,
                data=text,
            )

        try:
            data = json_loads(text)
        except JSONDecodeError as err:
            _LOGGER.error(
                "Failed to parse structured response: %s. Response: %s", err, text
            )
            raise HomeAssistantError(
                "OpenCode returned an invalid structured response"
            ) from err

        return ai_task.GenDataTaskResult(
            conversation_id=chat_log.conversation_id,
            data=data,
        )
