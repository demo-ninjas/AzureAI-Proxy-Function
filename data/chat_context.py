import os
import json 
import base64

import azure.functions as func
from pubsub import push_message
from .stream_message import StreamMessage
from .chunk_data import ChunkData
from .chat_config import ChatConfig, ChatFunctionConfig
from utils import read_first_matching_file

class ChatContext:
    req: func.HttpRequest = None
    body:dict = None
    thread_id:str = None
    linked_threads:dict[str,str] = None
    api_region: str = None
    api_version:str = None
    api_key: str = None
    api_endpoint:str = None
    system_prompt:str = None
    model:str = "gpt-4-32k"
    temperature:float = 0.0
    top_p:float = 1.0
    max_tokens:int = 1200
    timeout_secs:int = 90
    max_steps:int = 5
    max_history:int = 20

    config:ChatConfig = None
    stream_id:str = None
    stream_chunk:ChunkData = None

    def __init__(self, req: func.HttpRequest) -> None:
        self.req = req
        ## Body must be parsed first, as it can be used to set other values
        self.__parse_req_body(req)

        ## Next, Load the Chat Config - as it can also be used to set other values
        self.__load_chat_config(req)
        
        ## Then, Load the rest of the settings
        self.__load_oai_key(req)
        self.__load_temperature(req)
        self.__load_model(req)
        self.__load_timeout(req)
        self.__load_region(req)
        self.__load_endpoint(req)
        self.__load_version(req)
        self.__load_system_prompt(req)
        self.__load_stream_id(req)
        self.__load_max_steps(req)
        self.__load_max_history(req)
        self.__load_max_tokens(req)
        self.__load_top_p(req)

        ## Finally, parse the context variable (if provided) - This must be done last as it can override some of the already loaded settings
        self.__load_chat_context(req)
    
    def get_req_val(self, field:str, default_val:any = None) -> any:
        """
        Get a value from the body of the request, or return a default value if no value is provided for the field
        """

        val = None
        if self.body is not None: 
            val = self.body.get(field, None)
        if val is None:
            val = self.req.params.get(field, None)
        if val is None:
            val = self.req.route_params.get(field, None)
        if val is None:
            val = self.req.headers.get(field, None)
        return val if val is not None else default_val

    def get_linked_thread(self, assistant_id:str) -> str:
        """
        If there is a thread associated with the provided assistant, return the thread ID, otherwise None
        """
        if self.linked_threads is None: return None
        return self.linked_threads.get(assistant_id, None)
    
    def add_linked_thread(self, assistant:str, thread_id:str):
        """
        Save the thread ID for the provided assistant
        """
        if self.linked_threads is None: 
            self.linked_threads = dict()
        self.linked_threads[assistant] = thread_id

    def has_thread(self) -> bool:
        """
        Returns True if this context already has a thread ID associated with it (perhaps from previous requests related to this conversation)
        """
        return self.thread_id is not None
    

    def get_data_source_config_name(self) -> str:
        """
        If the current context requires usingn the Data Source extensions API, then this will return the name of the data source config that should be passed to the Extensions API 
        """
        ## If datasource config is disabled for this config, then return None
        if self.config is not None and self.config.use_data_source_config is False: 
            return None

        ## Find the data source config name from the request or the config or the environment variables
        ds_conf_name = self.get_req_val("data-source-config", None) or self.get_req_val("data-source", None)
        if ds_conf_name is None and self.config is not None and self.config.use_data_source_config:
            ds_conf_name = self.config.data_source_config
        if ds_conf_name is None: 
            ds_conf_name = os.environ.get('OAI_DATA_SOURCES_CONFIG_NAME', None)
        return ds_conf_name

    def get_function_config(self, function_name:str) -> ChatFunctionConfig:
        """
        Gets the configuration for the specified function, if it exists in the context's config
        """
        if self.config is None or self.config.functions is None: return False
        for f in self.config.functions:
            if f.name == function_name:
                return f
        return None

    def get_function_list(self) -> list[ChatFunctionConfig]:
        """
        Returns the list of functions that are configured in the context's config
        """
        return self.config.functions if self.config is not None else None


    def has_api_version(self) -> bool: 
        return self.api_version is not None
    
    def get_api_version(self) -> str: 
        return self.api_version
    
    def has_api_region(self) -> bool:
        return self.api_region is not None
    
    def get_api_region(self) -> str: 
        return self.api_region

    def has_api_endpoint(self) -> bool:
        return self.api_endpoint is not None
    
    def get_api_endpoint(self) -> str: 
        return self.api_endpoint

    def has_stream(self) -> bool: 
        return self.stream_id is not None

    def push_update_to_stream(self, message:StreamMessage):
        """
        Pushes the provided to the stream referenced by this context (if there is one, otherwise it does nothing)
        """
        if self.stream_id is not None:
            push_message(self.stream_id, message.to_message())
            
    def build_context(self)->str:
        """
        Build a context string that can be provided by subsequent requests to this API to maintain a conversation's context (thread).

        The context string is a base64 encoded JSON object containing the contextual data needed to continue the conversation
        """
        data = dict()
        if self.thread_id is not None:
            data['t'] = self.thread_id
        if self.api_region is not None:
            data['r'] = self.api_region
        if self.linked_threads is not None: 
            data['lt'] = self.linked_threads
        if self.model is not None:
            data['m'] = self.model
        
        ## TODO: Add any additional context that might be needed 
        return base64.urlsafe_b64encode(json.dumps(data).encode("utf-8")).decode("utf-8")

    def _unpack_context(self, context:str):
        """
        Unpacks the request context string (if provided) and sets the contextual data needed to continue an already active conversation
        """
        
        # Context is assumed to have been packed by the `build_context` method, essentially a b64 encoded json of the contextual data
        if context is None or len(context) == 0:
            self.thread_id = None
            self.linked_threads = None
        else:  
            padded_context = context + '=='
            unpacked = base64.urlsafe_b64decode(padded_context.encode("utf-8"))
            data = json.loads(unpacked)
            self.thread_id = data.get('t',None)
            self.linked_threads = data.get('lt', None)
            
            ## Region
            r = data.get('r', None)
            if r is not None: self.api_region = r
            
            ## Model
            m = data.get('m', None)
            if m is not None: self.model = m
            
            ## TODO: Add any additional context that might be needed 

    def __parse_req_body(self, req: func.HttpRequest):
         ## Grab the JSON body (if there is one)
        try: 
            if req.method == "POST":
                self.body = req.get_json()
            else: self.body = None
        except ValueError: self.body = None ## If the body isn't JSON, ignore it

    def __load_oai_key(self, req: func.HttpRequest):
        """
        Loads the Azure OpenAI API Key from the request headers, body, config, or environment variables
        """
        api_key_sources = [
            req.headers.get("openai-key", None),
            self.body.get('openai-key', None) if self.body else None,
            self.config.oai_key if self.config else None,
            os.getenv('AZURE_OAI_API_KEY', None),
        ]
        api_key = next((key for key in api_key_sources if key is not None and len(key.strip()) > 3), None)
        if not api_key:
            raise AssertionError("No API Key Available")
        self.api_key = api_key

    def __load_chat_context(self, req: func.HttpRequest):
        """
        Loads the context for this request from the request headers, body, or query parameters
        """
         ## Get the context for this request (if there is one)
        context_sources = [
            req.route_params.get('context', None),
            req.headers.get('context', None),
            self.body.get('context', None) if self.body else None,
            req.params.get('context', None)
        ]
        context = next((ctx for ctx in context_sources if ctx and len(ctx) > 3), None)
        self._unpack_context(context)
    
    def __load_temperature(self, req: func.HttpRequest):
        """
        Loads the temperature for the model from the request headers, body, config, or environment variables
        """
        sources = [
            req.headers.get("openai-model-temperature", None),
            self.body.get('openai-model-temperature', None) if self.body else None,
            self.config.temperature if self.config else None,
            os.getenv('AZURE_OAI_MODEL_TEMPERATURE', None),
        ]
        val = next((key for key in sources if key is not None), None)
        if not val:
            val = "0.0"  ## Default temperature
        self.temperature = float(val)
    
    def __load_region(self, req: func.HttpRequest):
        """
        Loads the Azure OpenAI API Region from the request headers, body, config, or environment variables
        """
        sources = [
            req.headers.get("openai-region", None),
            self.body.get('openai-region', None) if self.body else None,
            self.config.oai_region if self.config else None,
            os.getenv('AZURE_OAI_REGION', None),
        ]
        val = next((key for key in sources if key is not None and len(key.strip()) > 2), None)
        if not val:
            val = "australiaeast-01"  ## Default Region
        self.api_region = val

    def __load_version(self, req: func.HttpRequest):
        """
        Loads the Azure OpenAI API Version from the request headers, body, config, or environment variables
        """
        sources = [
            req.headers.get("openai-version", None),
            self.body.get('openai-version', None) if self.body else None,
            self.config.oai_version if self.config else None,
            os.getenv('AZURE_OAI_VERSION', None),
        ]
        val = next((key for key in sources if key is not None and len(key.strip()) > 2), None)
        if not val:
            val = "2024-02-15-preview"  ## Default Version
        self.api_version = val

    def __load_endpoint(self, req: func.HttpRequest):
        """
        Loads the Azure OpenAI API Endpoint from the request headers, body, config, or environment variables
        """
        sources = [
            req.headers.get("openai-endpoint", None),
            self.body.get('openai-endpoint', None) if self.body else None,
            self.config.oai_endpoint if self.config else None,
            os.getenv('AZURE_OAI_ENDPOINT', None),
        ]
        val = next((key for key in sources if key is not None and len(key.strip()) > 2), None)        
        self.api_endpoint = val ## Can be None

    def __load_model(self, req: func.HttpRequest):
        """
        Loads the Azure OpenAI Model from the request headers, body, config, or environment variables
        """
        sources = [
            req.headers.get("openai-model-deployment", None),
            self.body.get('openai-model-deployment', None) if self.body else None,
            req.params.get('model', None),
            self.config.oai_model if self.config else None,
            os.getenv('AZURE_OAI_MODEL_DEPLOYMENT', None),
        ]
        val = next((key for key in sources if key is not None and len(key.strip()) > 2), None)
        if not val:
            val = "gpt-4"  ## Default Model
        self.model = val

    def __load_timeout(self, req: func.HttpRequest):
        """
        Loads the timeout for the model from the request headers, body, config, or environment variables
        """
        sources = [
            req.headers.get("openai-model-timeout", None),
            self.body.get('openai-model-timeout', None) if self.body else None,
            req.params.get('openai-model-timeout', None),
            self.config.timeout_secs if self.config else None,
            os.getenv('AZURE_OAI_MODEL_TIMEOUT', None),
        ]
        val = next((key for key in sources if key is not None), None)
        if not val:
            val = "90"  ## Default timeout secs
        self.timeout_secs = int(val)

    def __load_stream_id(self, req: func.HttpRequest):
        """
        Loads the Stream ID from the request headers, body, or query parameters
        """
        sources = [
            req.headers.get("stream-id", None),
            self.body.get("stream-id", None) if self.body else None,
            req.params.get("stream-id", None),
        ]
        val = next((key for key in sources if key is not None), None)
        self.stream_id = val

    def __load_max_steps(self, req: func.HttpRequest):
        """
        Loads the max steps for the model from the request headers, body, config, or environment variables
        """
        sources = [
            req.headers.get("max-steps", None),
            self.body.get("max-steps", None) if self.body else None,
            req.params.get("max-steps", None),
            self.config.max_steps if self.config else None,
        ]
        val = next((key for key in sources if key is not None), None)
        if val is not None: 
            self.max_steps = int(val)
    
    def __load_max_history(self, req: func.HttpRequest):
        """
        Loads the max history for the model from the request headers, body, config, or environment variables
        """
        sources = [
            req.headers.get("max-history", None),
            self.body.get("max-history", None) if self.body else None,
            req.params.get("max-history", None),
            self.config.max_history if self.config else None,
        ]
        val = next((key for key in sources if key is not None), None)
        if val is not None: 
            self.max_history = int(val)

    def __load_max_tokens(self, req: func.HttpRequest):
        """
        Loads the max tokens for the model from the request headers, body, config, or environment variables
        """
        sources = [
            req.headers.get("max-tokens", None),
            self.body.get("max-tokens", None) if self.body else None,
            req.params.get("max-tokens", None),
            self.config.max_tokens if self.config else None,
        ]
        val = next((key for key in sources if key is not None), None)
        if val is not None: 
            self.max_tokens = float(val)

    def __load_top_p(self, req: func.HttpRequest):
        """
        Loads the top_p for the model from the request headers, body, config, or environment variables
        """
        sources = [
            req.headers.get("top-p", None),
            self.body.get("top-p", None) if self.body else None,
            req.params.get("top-p", None),
            self.config.top_p if self.config else None,
        ]
        val = next((key for key in sources if key is not None), None)
        if val is not None: 
            self.top_p = float(val)


    def __load_chat_config(self, req: func.HttpRequest):
        """
        Loads the Chat Config from the request headers, body, or query parameters
        """
        sources = [
            req.headers.get("config", None),
            req.params.get("config", None),
            self.body.get("config", None) if self.body else None,
        ]
        val = next((key for key in sources if key is not None and len(key.strip()) > 2), None)
        if val is not None: 
            self.config = ChatConfig.load(val)



    def __load_system_prompt(self, req: func.HttpRequest):
        """
        Loads the system prompt from the config. 
        If the config doesn't specify a system prompt, it checks if a prompt file has been specified in the request headers, body, or environment variables - if so, then it loads the prompt from that file.

        Note: The system prompt cannot be provided directly in the request, it must be provided in the config or a file
        """
        if self.config is not None and self.config.system_prompt is not None:
            self.system_prompt = self.config.system_prompt
        else: 
            curr_dir = os.path.dirname(os.path.realpath(__file__))

            ## Check list of paths and find the first existing path
            prompt_sources = [
                req.headers.get("prompt-file", None),
                self.body.get('prompt-file', None) if self.body else None,
                'system_prompt.txt',
                curr_dir + '/system_prompt.txt',
                os.environ.get('AZURE_OAI_SYSTEM_PROMPT_PATH', None),
            ]
            for path in prompt_sources:
                if path is not None:
                    if path.startswith('/') and not path.startswith(curr_dir):
                         raise ValueError(f"Invalid path specified for system prompt: {path}")
                    if '..' in path: 
                        raise ValueError(f"Invalid path specified for system prompt: {path}")
                    if os.path.exists(path):
                        with open(path, 'r') as f:
                            self.system_prompt = f.read()
                        break

            if self.system_prompt is None:
                self.system_prompt = os.environ.get('AZURE_OAI_SYSTEM_PROMPT', None)
