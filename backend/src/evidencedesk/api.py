from typing import Annotated

from fastapi import Depends, Query
from pydantic import BaseModel, ConfigDict

from evidencedesk.identity.service import Actor, authenticate

CurrentActor = Annotated[Actor, Depends(authenticate)]
PageLimit = Annotated[int, Query(ge=1, le=100)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
