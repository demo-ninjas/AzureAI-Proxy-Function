from time import time_ns

INTERIM_RESULT = "interim"
PROGRESS_UPDATE = "progress"
ERROR = "error"
INFO = "info"

class StreamMessage:
    content:any
    message_type:str
    timestamp:int

    def __init__(self, content:any, type:str) -> None:
        self.content = content
        self.message_type = type
        self.timestamp = time_ns() / 1000000    ## timestamp in milliseconds
        
    def to_message(self) -> dict:
        if type(self.content) is dict: 
            return {
                **self.content,
                "timestamp": self.timestamp,
                "type": self.message_type
            }
        else:  
            return {
                "message": self.content,
                "timestamp": self.timestamp,
                "type": self.message_type
            }