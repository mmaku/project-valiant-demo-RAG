import datetime

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from api.models.utils import (
    format_datetime_into_isoformat,
)


class BaseSchemaModel(BaseModel):
    model_config = ConfigDict(
        validate_assignment=True,
        populate_by_name=True,
        json_encoders={datetime.datetime: format_datetime_into_isoformat},
        alias_generator=to_camel,
    )
