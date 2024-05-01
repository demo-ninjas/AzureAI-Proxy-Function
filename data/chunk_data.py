import json
from typing import Tuple
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk, Choice as StreamChoice, ChoiceDelta, ChoiceDeltaFunctionCall, ChoiceDeltaToolCall, ChoiceDeltaToolCallFunction
from .chat_response import ChatCitation

class ChunkToolCallFunction:
    name:str = None
    arguments:str = None

class ChunkToolCallData:
    index:int = 0
    id:str = None
    type:str = None
    function:ChunkToolCallFunction = None

    def __init__(self):
        self.function = ChunkToolCallFunction()

class ChunkData:
    content:str = None
    role:str = None
    tool_calls:list[ChunkToolCallData] = None
    accumulated_delta:str = None
    last_stream_publish:int = 0

    tool_content = None

    def has_tool_citations(self) -> bool:
        if self.tool_content is not None: 
            if type(self.tool_content) is str: 
                tc = json.loads(self.tool_content)
                return tc.get("citations", None) is not None
    
    def get_tool_citations(self) -> list[ChatCitation]:
        if self.tool_content is not None: 
            if type(self.tool_content) is str: 
                tc = json.loads(self.tool_content)
                tc_citations = tc.get("citations", [])
                citations = []
                for tc_citation in tc_citations:
                    citation = ChatCitation()
                    if "id" in tc_citation: citation.id = tc_citation.get("id", None)
                    if "content" in tc_citation: citation.text = tc_citation.get("content", None)
                    if "title" in tc_citation: citation.title = tc_citation.get("title", None)
                    if "url" in tc_citation: citation.url = tc_citation.get("url", None)
                    if citation.url is None and "filepath" in tc_citation: citation.url = tc_citation.get("filepath", None)
                    if "end" in tc_citation: citation.end = tc_citation.get("end", None)
                    if "start" in tc_citation: citation.start = tc_citation.get("start", None)
                    citations.append(citation)
                return citations
        return None

    def add_data_source_delta(self, data_source_delta_msgs:list[any]) -> Tuple[bool, bool]:
        """
        Process any delta messages from the data extensions API, updating the chunk data with any new content from the delta messages.
        Returns a tuple of (end_turn, content_accumulated) where end_turn is a boolean indicating if the turn has ended and content_accumulated is a boolean indicating if any content was accumulated from the messages.
        """
        end_turn = False
        content_accumulated = False
        for msg in data_source_delta_msgs:
            delta = msg.get('delta', None)
            if delta is None: continue
            role = delta.get('role', None)
            if role is None: 
                ## Receiving content
                content = delta.get('content', None)
                if content is None: continue
                self.content = content if self.content is None else self.content + content
                self.accumulated_delta = content if self.accumulated_delta is None else self.accumulated_delta + content
                content_accumulated = True
            elif role == 'tool':
                content = delta.get('content', None)
                if content is None: continue
                self.tool_content = content if self.tool_content is None else self.tool_content + content
            elif role == 'assistant': 
                print("Assistant Delta:", delta)
            else: 
                raise ValueError(f"Data Source Delta message with unexpected role: {msg.role}", data_source_delta_msgs)
            end_turn = msg.get('end_turn', False)
        return (end_turn, content_accumulated)
        
    def add_chunk_delta(self, delta:ChoiceDelta):
        """
        Process the delta message recieved from the completions API, updating the chunk data with any the new content.
        """
        if delta.role is not None: 
            self.role = delta.role
        
        if delta.content is not None:
            self.content = delta.content if self.content is None else self.content + delta.content
            self.accumulated_delta = delta.content if self.accumulated_delta is None else self.accumulated_delta + delta.content
        
        if delta.tool_calls is not None: 
            if self.tool_calls is None: self.tool_calls = []
            for delta_tool in delta.tool_calls:
                ## Find the matching tool call in the tool_calls list
                tool_call = None
                for self_tool_call in self.tool_calls:
                    if self_tool_call.index == delta_tool.index:
                        tool_call = self_tool_call                            
                        break
                
                if tool_call is None: 
                    tool_call = ChunkToolCallData()
                    self.tool_calls.append(tool_call)

                if tool_call.type == "function" or delta_tool.type == "function":
                    tool_call.index = delta_tool.index
                    if delta_tool.id is not None: tool_call.id = delta_tool.id
                    if delta_tool.type is not None: tool_call.type = delta_tool.type
                    if delta_tool.function.name is not None: tool_call.function.name = delta_tool.function.name
                    if delta_tool.function.arguments is not None: tool_call.function.arguments = delta_tool.function.arguments if tool_call.function.arguments is None else tool_call.function.arguments + delta_tool.function.arguments
                else: 
                    raise ValueError(f"Unknown tool call type: {delta_tool.type}")
            