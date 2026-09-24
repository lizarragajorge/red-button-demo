"""Azure Functions v2 entry point for inventory, work and poison diagnostics."""

import logging
import os
from uuid import UUID

import azure.functions as func

from server.config import Settings
from server.execution import execute_request, refresh_inventory
from server.runtime import upstream_client
from server.storage import AzureRepository

app = func.FunctionApp()
log = logging.getLogger(__name__)


async def process_message(message: func.QueueMessage, *, poison=False):
    try:
        request_id = str(UUID(message.get_body().decode("utf-8")))
    except (UnicodeError, ValueError):
        # Malformed messages have no trustworthy correlation or actor information.
        log.error("Discarding malformed request queue message; poison=%s", poison)
        return
    settings = Settings.from_env()
    repository = AzureRepository(settings)
    try:
        async with upstream_client(settings, repository) as client:
            await execute_request(repository, client, settings, request_id, poison=poison)
    finally:
        await repository.close()


@app.timer_trigger(
    schedule=os.environ.get("INVENTORY_REFRESH_SCHEDULE", "0 */5 * * * *"),
    arg_name="timer", run_on_startup=False, use_monitor=True,
)
async def inventory_refresh(timer: func.TimerRequest):
    settings = Settings.from_env()
    if settings.execution_mode != "queued":
        return
    repository = AzureRepository(settings)
    try:
        async with upstream_client(settings, repository) as client:
            await refresh_inventory(repository, client, settings)
    finally:
        await repository.close()


@app.queue_trigger(arg_name="message", queue_name="requests", connection="WORK_STORAGE")
async def request_worker(message: func.QueueMessage):
    await process_message(message)


@app.queue_trigger(arg_name="message", queue_name="requests-poison", connection="WORK_STORAGE")
async def request_poison(message: func.QueueMessage):
    await process_message(message, poison=True)
