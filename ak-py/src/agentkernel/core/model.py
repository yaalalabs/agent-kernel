from typing import Any, Literal, Union
from pydantic import BaseModel



class AgentRequestText(BaseModel):
    """
    AgentRequestText encapsulates a text request to an agent.
        
    text: str  : This is the user input text
    type: Literal["text"]
    """
    text: str
    type: Literal["text"]
    def __init__(self, *args: Any, **kwds: Any):
        self.type = "text"
        return super().__init__(*args, **kwds)
    
class AgentRequestFile(BaseModel):
    """
    AgentRequestFile encapsulates a file attachment request to an agent
    
    file_data: str  : This could be base64 encoded string or url
    name: str : name of the file
    type: Literal["file"]
    mime_type: str | None = None : Optional MIME The IANA standard MIME type of
    """
    file_data: str  # This could be base64 encoded string or url
    name: str
    type: Literal["file"]
    mime_type: str | None = None # Optional MIME The IANA standard MIME type of the source data
    
    def __init__(self, *args: Any, **kwds: Any):
        self.type = "file"
        return super().__init__(*args, **kwds)
    
class AgentRequestImage(BaseModel):
    """
    AgentRequestImage encapsulates an image request to an agent
    
    image_data: str  : This should be base64 encoded string
    name: str : name of the image
    type: Literal["image"]
    mime_type: str | None = None : Optional MIME The IANA standard MIME type of
    """
    image_data: str
    name: str
    type: Literal["image"]
    mime_type: str | None = None 

    def __init__(self, *args: Any, **kwds: Any):
        self.type = "image"
        return super().__init__(*args, **kwds)  
    
class AgentRequestAny(BaseModel):
    """
    AgentRequestAny encapsulates a passing any type of request to be handled by the pre-execution hooks. These are not directly handled by the agent kernel runtime.
   
    any_data: Any : This could be base64 encoded string or bytes or url
    name: str : name of the data
    type: Literal["other"]
    """
    content: Any
    name: str
    type: Literal["other"]

    def __init__(self, *args: Any, **kwds: Any):
        self.type = "other"
        return super().__init__(*args, **kwds)
    
class AgentReplyText(AgentRequestText):
    """
    AgentReplyText encapsulates a text reply from an agent.
        
    text: str  : This is the agent output text
    type: Literal["text"]
    """
    text: str
    type: Literal["text"]
    def __init__(self, *args: Any, **kwds: Any):
        return super().__init__(*args, **kwds)  
    
type AgentRequest = Union[AgentRequestText, AgentRequestFile, AgentRequestImage, AgentRequestAny]
type AgentReply = Union[str, AgentReplyText, dict]