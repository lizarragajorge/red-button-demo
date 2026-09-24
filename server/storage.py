"""Private durable JSON blobs, conditional writes, leases and queue delivery."""

import asyncio
import copy
import json
import time
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from typing import AsyncContextManager, Protocol
from uuid import uuid4

from .config import Settings

REQUEST_LEASE_RENEWAL_SECONDS = 20


class Conflict(Exception):
    """A conditional write or exclusive lease lost a race."""


class StorageUnavailable(Exception):
    pass


@dataclass
class Document:
    value: dict
    etag: str


class Repository(Protocol):
    async def read(self, container: str, key: str) -> Document | None: ...
    async def create(self, container: str, key: str, value: dict) -> Document: ...
    async def replace(self, container: str, key: str, value: dict, etag: str, lease: str | None = None) -> Document: ...
    async def delete(self, container: str, key: str, etag: str) -> None: ...
    def lease(self, container: str, key: str) -> AsyncContextManager[str]: ...
    async def enqueue(self, request_id: str) -> None: ...
    async def close(self) -> None: ...


class AzureRepository:
    """Uses existing private containers/queues; never provisions resources."""

    def __init__(self, settings: Settings):
        from azure.identity.aio import ManagedIdentityCredential
        from azure.storage.blob.aio import BlobServiceClient
        from azure.storage.queue import TextBase64EncodePolicy
        from azure.storage.queue.aio import QueueClient

        self.credential = None
        if settings.storage_connection_string:
            self.blobs = BlobServiceClient.from_connection_string(settings.storage_connection_string, retry_total=0)
            self.queue = QueueClient.from_connection_string(
                settings.storage_connection_string, "requests", retry_total=0,
                message_encode_policy=TextBase64EncodePolicy(),
            )
        elif settings.storage_account_name:
            self.credential = ManagedIdentityCredential()
            self.blobs = BlobServiceClient(
                f"https://{settings.storage_account_name}.blob.core.windows.net",
                credential=self.credential, retry_total=0,
            )
            self.queue = QueueClient(
                f"https://{settings.storage_account_name}.queue.core.windows.net", "requests",
                credential=self.credential, retry_total=0, message_encode_policy=TextBase64EncodePolicy(),
            )
        else:
            raise StorageUnavailable("Queued execution requires storage configuration.")

    def blob(self, container, key):
        return self.blobs.get_blob_client(container, key)

    @staticmethod
    def translate(error):
        if getattr(error, "status_code", None) in (409, 412):
            return Conflict()
        return StorageUnavailable("Durable storage is unavailable.")

    async def read(self, container, key):
        from azure.core.exceptions import AzureError, ResourceNotFoundError
        try:
            stream = await self.blob(container, key).download_blob()
            return Document(json.loads(await stream.readall()), stream.properties.etag)
        except ResourceNotFoundError:
            return None
        except AzureError as error:
            raise self.translate(error) from None

    async def create(self, container, key, value):
        from azure.core.exceptions import AzureError
        try:
            result = await self.blob(container, key).upload_blob(json.dumps(value), overwrite=False)
            return Document(copy.deepcopy(value), result["etag"])
        except AzureError as error:
            raise self.translate(error) from None

    async def replace(self, container, key, value, etag, lease=None):
        from azure.core import MatchConditions
        from azure.core.exceptions import AzureError
        try:
            result = await self.blob(container, key).upload_blob(
                json.dumps(value), overwrite=True, etag=etag,
                match_condition=MatchConditions.IfNotModified, lease=lease,
            )
            return Document(copy.deepcopy(value), result["etag"])
        except AzureError as error:
            raise self.translate(error) from None

    async def delete(self, container, key, etag):
        from azure.core import MatchConditions
        from azure.core.exceptions import AzureError
        try:
            await self.blob(container, key).delete_blob(etag=etag, match_condition=MatchConditions.IfNotModified)
        except AzureError as error:
            raise self.translate(error) from None

    @asynccontextmanager
    async def lease(self, container, key):
        from azure.core.exceptions import AzureError
        try:
            lease = await self.blob(container, key).acquire_lease(lease_duration=60)
        except AzureError as error:
            raise self.translate(error) from None

        async def renew():
            while True:
                await asyncio.sleep(REQUEST_LEASE_RENEWAL_SECONDS)
                await lease.renew()

        renewal = asyncio.create_task(renew())
        try:
            yield lease.id
        finally:
            renewal.cancel()
            with suppress(asyncio.CancelledError, AzureError):
                await renewal
            with suppress(AzureError):
                await lease.release()

    async def enqueue(self, request_id):
        from azure.core.exceptions import AzureError
        try:
            await self.queue.send_message(request_id)
        except AzureError:
            raise StorageUnavailable("Queue delivery could not be confirmed.") from None

    async def close(self):
        await self.queue.close()
        await self.blobs.close()
        if self.credential:
            await self.credential.close()


class MemoryRepository:
    """Test double with copy isolation, ETag CAS, lease enforcement and queue."""

    def __init__(self):
        self.documents = {}
        self.leases = {}
        self.messages = []
        self.enqueue_failure = False

    async def read(self, container, key):
        return copy.deepcopy(self.documents.get((container, key)))

    def check_lease(self, path, token=None):
        lease = self.leases.get(path)
        if lease and lease[1] <= time.monotonic():
            self.leases.pop(path)
            lease = None
        if (lease and lease[0] != token) or (token and not lease):
            raise Conflict()

    async def create(self, container, key, value):
        path = (container, key)
        if path in self.documents:
            raise Conflict()
        doc = Document(copy.deepcopy(value), str(uuid4()))
        self.documents[path] = doc
        return copy.deepcopy(doc)

    async def replace(self, container, key, value, etag, lease=None):
        path = (container, key)
        self.check_lease(path, lease)
        if path not in self.documents or self.documents[path].etag != etag:
            raise Conflict()
        doc = Document(copy.deepcopy(value), str(uuid4()))
        self.documents[path] = doc
        return copy.deepcopy(doc)

    async def delete(self, container, key, etag):
        path = (container, key)
        self.check_lease(path)
        if path not in self.documents or self.documents[path].etag != etag:
            raise Conflict()
        del self.documents[path]

    @asynccontextmanager
    async def lease(self, container, key):
        path = (container, key)
        self.check_lease(path)
        if path not in self.documents:
            raise Conflict()
        token = str(uuid4())
        self.leases[path] = (token, float("inf"))
        try:
            yield token
        finally:
            if self.leases.get(path, (None,))[0] == token:
                del self.leases[path]

    async def enqueue(self, request_id):
        if self.enqueue_failure:
            raise StorageUnavailable("Queue delivery could not be confirmed.")
        self.messages.append(request_id)

    async def close(self):
        pass
