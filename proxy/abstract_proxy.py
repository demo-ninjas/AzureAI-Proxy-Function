import os
from time import sleep, time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
from typing import abstractmethod


from openai import AzureOpenAI
from openai.types.beta.threads.run_submit_tool_outputs_params import ToolOutput

from data import ChatContext, ChatResponse

from function_registry import FunctionRegistry, GLOBAL_FUNCTIONS_REGISTRY

class AbstractProxy:
    _context:ChatContext

    def __init__(self, context:ChatContext) -> None:
        global GLOBAL_FUNCTIONS_REGISTRY
        self._context = context
        self._func_registry = GLOBAL_FUNCTIONS_REGISTRY
        self._tools = self._func_registry.generate_tools_definition(context.get_function_list())
        self._default_region = "australiaeast-01"
        self._api_version = context.get_api_version()
        self._client = AzureOpenAI(
            azure_endpoint = self._build_base_url(False), 
            api_key=self._context.api_key,  
            api_version=self._api_version
        )

        logging.getLogger("httpx").setLevel(logging.ERROR) ## Stop the excessive logging from the httpx client library  

    @abstractmethod
    def send_message(self, message:str, in_thread:str = None, timeout_secs:int = 5, metadata:dict[str,str] = None) -> ChatResponse:
        """
        Send a user message and return the response to the message
        """
        raise NotImplementedError("This method must be implemented by the subclass")


    @abstractmethod
    def _create_thread(self, metadata:dict[str,str] = None) -> str:
        """
        Create a new thread and return the thread id 
        
        (this must be implemented by the subclass as the concept of a thread differs between different APIs)
        """
        raise NotImplementedError("This method must be implemented by the subclass")


    def _build_base_url(self, include_path:bool = True)->str:
        if self._context.has_api_endpoint():
            return self._context.get_api_endpoint()
        else: 
            region = self._context.get_api_region() or self._default_region
            return f"https://aoai-{region}.openai.azure.com/{'openai' if include_path else ''}"

    def _determine_thread_id(self, override_thread:str = None, for_assistant:str = None) -> str: 
        ## Use the provided thread or default to the context thread
        thread_id = override_thread
        if thread_id is None:
            ## Check if there's a specific thread for the assistant
            if for_assistant is not None:
                thread_id = self._context.get_linked_thread(for_assistant)
            
            ## If the thread is still None, and there's no thread in the context, then create one
            if thread_id is None and not self._context.has_thread():
                thread_id = self._create_thread()
                self._context.thread_id = thread_id
            
            ## If the thread is still None, then use the main thread
            if thread_id is None:
                thread_id = self._context.thread_id
        
        if thread_id is None: 
            raise ValueError("No thread ID available")
        return thread_id
    

    def _invoke_function_tool(self, function_name:str, *args, **kwargs) -> any:
        ## Check if the function is in the context config
        matched_function = self._context.get_function_config(function_name)
        if matched_function is not None:
            kwargs.update(matched_function.args)    ## Add the pre-configured args to the kwargs
            return self._func_registry[matched_function.function](*args, **kwargs) 

        ## Next, check if the function is a base function that has been registered in the registry
        if function_name in self._func_registry: 
            return self._func_registry[function_name](*args, **kwargs)
        else: 
            raise ValueError(f"No function tool registered with the name: {function_name}")