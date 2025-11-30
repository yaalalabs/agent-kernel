from typing import Any, Literal, Union

from pydantic import BaseModel


class AgentRequestText(BaseModel):
    """
    AgentRequestText encapsulates a text request to an agent.

    text: str  : This is the user input text
    type: Literal["text"]
    """

    text: str
    type: Literal["text"] = "text"

    def __str__(self) -> str:
        return self.text


class AgentRequestFile(BaseModel):
    """
    AgentRequestFile encapsulates a file attachment request to an agent

    file_data: str  : This could be base64 encoded string or url
    name: str : name of the file
    type: Literal["file"]
    mime_type: str | None = None : Optional. The IANA standard MIME type of the file
    """

    file_data: str  # This could be base64 encoded string or url
    name: str
    type: Literal["file"] = "file"
    mime_type: str | None = None  # Optional. The IANA standard MIME type of the source data


class AgentRequestImage(BaseModel):
    """
    AgentRequestImage encapsulates an image request to an agent

    image_data: str  : This should be base64 encoded string
    name: str : name of the image
    type: Literal["image"]
    mime_type: str | None = None : Optional. The IANA standard MIME type of the image
    """

    image_data: str
    name: str
    type: Literal["image"] = "image"
    mime_type: str | None = None


class AgentRequestAny(BaseModel):
    """
    AgentRequestAny encapsulates passing any type of request to be handled by the pre-execution hooks. These are not directly handled by the agent kernel runtime.

    content: Any : This could be base64 encoded string or bytes or url
    name: str : name of the data
    type: Literal["other"]
    """

    content: Any
    name: str
    type: Literal["other"] = "other"


class AgentReplyText(AgentRequestText):
    """
    AgentReplyText encapsulates a text reply from an agent.

    prompt: str : The text prompt sent to the agent

    Inherits fields `text` and `type` from AgentRequestText.
    """

    prompt: str = ""

    def __str__(self) -> str:
        return self.text


class AgentReplyImage(BaseModel):
    """
    AgentReplyImage encapsulates a text & image reply from an agent.

    text: str  : This is the agent output text
    prompt: str : The text prompt sent to the agent
    image_data: str  : This should be base64 encoded string
    name: str : name of the image
    type: Literal["image"]
    mime_type: str | None = None : Optional. The IANA standard MIME type of the image
    """

    text: str
    prompt: str = ""
    image_data: str
    name: str
    type: Literal["image"] = "image"
    mime_type: str | None = None

    def __str__(self) -> str:
        return f"{self.text}. Image {self.name} is attached."


type AgentRequest = Union[AgentRequestText, AgentRequestFile, AgentRequestImage, AgentRequestAny]
type AgentReply = Union[AgentReplyText, AgentReplyImage]
