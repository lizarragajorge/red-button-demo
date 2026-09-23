from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

ServerId = Annotated[int, Field(strict=True, gt=0, le=2147483647)]
NonnegativeInt32 = Annotated[int, Field(strict=True, ge=0, le=2147483647)]


class DelayOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enable_after_a_delay: NonnegativeInt32 | None = Field(None, alias="enableAfterADelay")
    enable_after_delay_time_zone: NonnegativeInt32 | None = Field(None, alias="enableAfterDelayTimeZone")

    @model_validator(mode="after")
    def timezone_requires_timestamp(self):
        if self.enable_after_delay_time_zone is not None and self.enable_after_a_delay is None:
            raise ValueError("A timezone requires enableAfterADelay.")
        return self


class DisableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    server_ids: list[ServerId] = Field(alias="serverIds", min_length=1, max_length=50)
    confirmation: str
    options: DelayOptions = Field(default_factory=DelayOptions)

    @model_validator(mode="after")
    def confirm_unique_targets(self):
        if self.confirmation != "DISABLE BACKUPS":
            raise ValueError("Type DISABLE BACKUPS to confirm.")
        if len(set(self.server_ids)) != len(self.server_ids):
            raise ValueError("Server IDs must be unique.")
        return self


class ServerRecord(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    id: ServerId
    name: str
    displayName: str | None = None
    hostName: str | None = None
    OS: str | None = None
    isInfrastructure: bool | None = None


class ServerList(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    totalServers: NonnegativeInt32
    servers: list[ServerRecord]


class ActionResult(BaseModel):
    model_config = ConfigDict(strict=True)
    errorCode: Annotated[int, Field(strict=True, ge=-2147483648, le=2147483647)]
    errorMessage: str | None = None
