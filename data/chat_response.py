
class ChatCitation: 
    id: str|None = None
    """The ID of the citation."""
    text: str|None = None
    """The text of the citation."""
    url: str|None = None
    """The URL of the citation."""
    title: str|None = None
    """The title of the citation."""
    start: int|None = None
    """The start index of the citation in the message."""
    end: int|None = None
    """The end index of the citation in the message."""
    replace_part: str|None = None
    """The part of the message that the citation replaces / is the reference for."""

    def to_api_response(self) -> dict:
        out = dict()
        if self.id is not None: out["id"] = self.id
        if self.text is not None: out["content"] = self.text
        if self.url is not None: out["url"] = self.url
        if self.title is not None: out["title"] = self.title
        if self.start is not None: out["start"] = self.start
        if self.end is not None: out["end"] = self.end
        if self.replace_part is not None: out["replace_part"] = self.replace_part
        return out
    
    def from_data_source_citation(datasorce_citation:dict) -> 'ChatCitation': 
        citation = ChatCitation()
        if "id" in datasorce_citation: citation.id = datasorce_citation.get("id", None)
        if "content" in datasorce_citation: citation.text = datasorce_citation.get("content", None)
        if "title" in datasorce_citation: citation.title = datasorce_citation.get("title", None)
        if "url" in datasorce_citation: citation.url = datasorce_citation.get("url", None)
        if citation.url is None and "filepath" in datasorce_citation: citation.url = datasorce_citation.get("filepath", None)
        if "end" in datasorce_citation: citation.end = datasorce_citation.get("end", None)
        if "start" in datasorce_citation: citation.start = datasorce_citation.get("start", None)
        return citation

class ChatResponse:
    id: str|None = None
    """The ID of the message (if one has been assigned to it)."""
    
    thread_id: str|None = None
    """The ID of the thread that this message is part of."""

    assistant_id: str|None = None
    """The ID of the assistant that generated this message (if using Assistants)."""

    message: str|None = None
    """The message response."""

    citations: list[ChatCitation]|None = None
    """A list of citations for the response."""

    intent: str|None = None
    """The interpreted intent of the user."""

    metadata: dict[str,any]|None = None
    """Metadata associated with the response."""

    def to_api_response(self) -> dict:
        out = dict()
        if self.id is not None: out["id"] = self.id
        if self.assistant_id is not None: out["assistant-id"] = self.assistant_id
        if self.message is not None: out["message"] = self.message
        if self.citations is not None: out["citations"] = [c.to_api_response() for c in self.citations]
        if self.intent is not None: out["intent"] = self.intent
        if self.metadata is not None: 
            for k,v in self.metadata.items(): out[k] = v
        return out
