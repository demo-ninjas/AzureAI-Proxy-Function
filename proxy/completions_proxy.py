import os
from time import time
import json
import logging
from uuid import uuid4 

import openai
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk, Choice as StreamChoice
from openai.types.chat import ChatCompletionMessageToolCall

from data import ChatContext, ChatResponse, StreamMessage, ChunkData, PROGRESS_UPDATE, INTERIM_RESULT, ChatCitation
from functions import get_item, upsert_item
from .completions_extensions_adapter import CompletionsWithExtensionsAdapter
from .abstract_proxy import AbstractProxy
from utils import load_named_config

class CompletionsProxy(AbstractProxy):
    def __init__(self, context:ChatContext) -> None:
        super().__init__(context)
        self.__load_oai_data_source_config()
        self.history = None
    
    def _create_thread(self, metadata: dict[str, str] = None) -> str:
        ## Create a new Thread ID
        thread_id = uuid4().hex

        ## Setup new History
        self._init_history(thread_id, metadata)
        
        return thread_id
    
    def send_message(self, message:str, in_thread:str = None, timeout_secs:int = 5, metadata:dict[str,str] = None) -> ChatResponse:
        ## Use the provided thread, the context thread, or create a new one
        thread_id = self._determine_thread_id(override_thread=in_thread)
        ## Add the user message to the thread history
        self._context.push_update_to_stream(StreamMessage("Recalling our conversation so far", PROGRESS_UPDATE))
        self._add_user_prompt_to_thread(message, role="user", thread_id=thread_id)
        
        ## If the length of the conversation is getting long, summarise the conversation and drop the history
        if len(self.history.get('messages', [])) >= self._context.max_history:
            self.__summarise_thread( metadata)

        ## Create the response object
        response = ChatResponse()
        response.thread_id = thread_id
        
        ## Continuously send messages to the model until we get a final response
        more_steps = True
        step_count = 0
        should_stream_results = self._context.has_stream()
        while more_steps and step_count < self._context.max_steps:
            step_count += 1

            ## Build the Message list from the history
            messages = [
                    {key: value for key, value in history_item.items() if key not in ['ts', 'citations']} 
                    for history_item in self.history.get('messages', [])
                ]
            
            ## Send a progress Update
            if step_count == 1:
                self._context.push_update_to_stream(StreamMessage("Thinking about what you said", PROGRESS_UPDATE))
            else: 
                self._context.push_update_to_stream(StreamMessage("Analysing the data I've collected so far", PROGRESS_UPDATE))


            if self.completions_data_sources is not None:
                ## Pass a data source configuration to the Completions API and let it do the RAG operations itself
                ## This approach simplifies the work done by this function, but is limited to only supporting the 
                ## data sources and operations supported by the Azure OpenAI Data Sources API 
                result = self.completions_adapter.client().chat.completions.create(
                    messages=messages,
                    model=self._context.model,
                    temperature=self._context.temperature,
                    extra_body={ "dataSources": self.completions_data_sources},
                    timeout=self._context.timeout_secs,
                    top_p=self._context.top_p,
                    max_tokens=self._context.max_tokens,
                    stop=None,
                    stream=should_stream_results,
                )
            else: 
                ## Pass a tool configuration to the Completions API and handle the RAG + other function calls ourselves
                ## This approach allows for more flexibility in the data sources and operations that can be supported, 
                ## essentially allowing for any function to be called and any data source to be queried :) 
                result = self._client.chat.completions.create(
                    messages=messages, 
                    model=self._context.model,
                    temperature=self._context.temperature,
                    max_tokens=self._context.max_tokens,
                    top_p=self._context.top_p,
                    tools=self._tools,
                    tool_choice="auto" if step_count < self._context.max_steps - 1 else "none",
                    timeout=self._context.timeout_secs,
                    stream=should_stream_results,
                )

            ## Process the resopnse from the model
            if type(result) is openai.Stream:
                more_steps = self.__handle_stream_result(result, response)
            else: 
                more_steps = self.__process_choices(result, response) 
        
        ## Write the History Item back to the CosmosDB (with the updated messages list)
        self._context.push_update_to_stream(StreamMessage("Documenting our conversation", PROGRESS_UPDATE))
        self._save_thread()

        return response

    def _init_history(self, thread_id:str, metadata: dict[str, str] = None): 
        if self.history is None:
            ## Setup the System Prompt
            system_prompt = self._get_system_prompt(metadata)
            self.history = {
                "id": "history",
                "partitionKey": thread_id,
                "type": "thread",
                "messages": [{
                    "ts": int(time()*1000.0),   ## in millis
                    "content": system_prompt,
                    "role": "system"
                }],
                "metadata": {}
            }
    
    def _retrieve_thread(self, thread_id:str) -> dict:
        ## Retrieve the thread history from CosmosDB
        return get_item("history", thread_id)
    
    def _save_thread(self):
        if self.history is not None:
            upsert_item(self.history)

    def _get_system_prompt(self, metadata: dict[str, str] = None) -> str:
        ## Get System from context
        system_prompt = self._context.system_prompt
        
        ## If there is no system prompt in the context, then set a default generic prompt
        if system_prompt is None:
            system_prompt = "You are a smart assistant who is here to answer user questions as best you can."
        return system_prompt

    def _publish_interim_result(self, force_publish:bool = False, publish_frequency:float = 0.4): 
        if force_publish or time() - self._context.stream_chunk.last_stream_publish > publish_frequency:
            if self._context.stream_chunk.accumulated_delta is not None and len(self._context.stream_chunk.accumulated_delta) > 0: ## Only publish if there is actually something to publish
                self._context.push_update_to_stream(StreamMessage({ "delta": self._context.stream_chunk.accumulated_delta }, INTERIM_RESULT))
                self._context.stream_chunk.last_stream_publish = time()
                self._context.stream_chunk.accumulated_delta = None
    
    def _add_user_prompt_to_thread(self, message:str, role:str = "user", thread_id:str = None):
        ## If no history is provided, then retrieve the history from the CosmosDB
        if not self.history:
            if not thread_id:
                raise ValueError("Either thread_id or thread_history must be provided")
            ## Retrieve Thread History from the CosmosDB 
            self.history = self._retrieve_thread(thread_id)
            if self.history is None:
                self._init_history(thread_id)
        
        ## Add the message to the history
        self.history["messages"].append({
            "ts": int(time()*1000.0),   ## in millis
            "content": message,
            "role": role
        })
    
    def _add_message_to_thread(self, message:dict): 
        message["ts"] = int(time()*1000.0)   ## in millis
        self.history.get('messages', []).append(message)

    def __summarise_thread(self, metadata:dict[str,str] = None): 
        self._context.push_update_to_stream(StreamMessage("I'm just summarising the conversation so far", PROGRESS_UPDATE))
        
        ## Grab all the messages in the History so far
        messages = self.history.get('messages', [])
        
        ## Pop the last two messages from the list
        most_recent_message = messages.pop()
        second_most_recent_message = messages.pop()

        ## Add a prompt requesting a summary of the conversation
        self._add_message_to_thread({
             "content": "Summarize the key points from this whole conversation, keeping track of important information that may be needed to continue the conversation at a later point. Be as consise as possible, but don't stinge out on the details either",
            "role": "user"
        })
        
        ## Send the messages to the model to get a summary
        result = self._client.chat.completions.create(
            messages=[
                {key: value for key, value in message.items() if key != 'ts'} 
                for message in self.history.get('messages', [])
            ], 
            model=self._context.model,
            temperature=self._context.temperature,
            max_tokens=self._context.max_tokens,
            top_p=self._context.top_p,
            tools = self._tools,    ## Including the tools so that the AI knows about what the functions that have been previously called actually do
            tool_choice="none",     ## But, turn off using the tools, because we don't want to call any functions here
            timeout=self._context.timeout_secs,
        )


        ## Now, setup the new History
        system_prompt = self._get_system_prompt(metadata)
        self.history.get('messages', []).clear()
        if system_prompt is not None: 
            self._add_message_to_thread({ "content": system_prompt, "role": "system" })

        ## Add the summary response from the model
        for choice in result.choices:
            ## Add message to history and return the message
            self._add_message_to_thread({
                "content": "Here is a summary of the conversation up to this point: " + choice.message.content,
                "role": choice.message.role
            })
        ## And put the most recent 2 messages back in the history (this includes the current prompt that this request is actually for) 
        self._add_message_to_thread(second_most_recent_message)
        self._add_message_to_thread(most_recent_message)

    def __process_choices(self, result, response:ChatResponse) -> bool:
        ### Process the Choices from the AI Model
        more_steps = True

        if len(result.choices) > 1: 
            ## First, if there are multiple choices, sort them by the index field
            result.choices = sorted(result.choices, key=lambda x: x.index if x.index else 0)

        for choice in result.choices:
            if type(choice) is StreamChoice:
                ## Record the next chunk from the stream and continue
                more_steps = self.__process_stream_chunk(choice, response)
            elif choice.model_extra is not None and choice.model_extra.get('messages') is not None: 
                ## Process the messages from the model_extra - this is a special case for the OpenAI Data Sources API
                self.__process_data_source_api_response(choice.model_extra.get('messages'), response)
                pass
            elif choice.message is None: 
                logging.warning(f"No message in choice: {choice} [Not doing anything with it atm.]") ## TODO: Check if we should do something with this choice or just simply continue?!
                continue   ## No message yet, so continue
            elif choice.message.tool_calls is not None and len(choice.message.tool_calls) > 0:
                ## Process Tool Calls
                ## Put the tool call into the history, it needs to be in the history when we return the tool response back to the AI
                self._add_message_to_thread({
                        "tool_calls": [{ "id":tool.id, "function":{ "arguments":tool.function.arguments, "name":tool.function.name }, "type":"function" } for tool in choice.message.tool_calls],
                        "role": choice.message.role
                    })
                self.__process_tool_calls(choice.message.tool_calls)
            else: 
                ## This is a normal message from the AI
                ## So, grab the content, add it to the hsitory and return the message
                self._add_message_to_thread({ "content": choice.message.content, "role": choice.message.role })
                response.message = choice.message.content if response.message is None else response.message + "\n" + choice.message.content
                more_steps = False  ## We've got the response from the AI, so no more steps 

        return more_steps

    def __process_data_source_api_response(self, messages, response:ChatResponse) -> bool:
        ### Process the response from the Azure OpenAI Data Sources API
        ## There will be multiple messages in this response

        more_steps = True
        msg_content = None
        msg_citations = []
        for message in messages:
            role = message.get('role', None)
            if role and role == 'assistant': 
                ## This is content from the backing assistant, add it to the message content
                msg_content = message.get('content', '')
            elif role and role == 'tool':
                ## This is usually the citations from the tool 
                tool_content = message.get('content', '')
                if tool_content is not None and tool_content.startswith("{"):
                    tool_content = json.loads(tool_content)
                    if "citations" in tool_content:
                        msg_citations.extend(tool_content["citations"])
                    else: 
                        logging.warning(f"Tool Content from Data Source API: {tool_content} [Not doing anything with it atm.]")

            ## If this is the end of the turn, then we're done, so set more_steps to False
            if message.get('end_turn') == True:
                more_steps = False

            ## This API can return an intent, grab it if it's there
            user_intent = message.get('intent', None)
            if user_intent is not None: 
                response.intent = user_intent if response.intent is None else response.intent + "\n" + user_intent

        ## If we recieved a message from the assistant, then add it to the response
        if msg_content is not None: 
            response.message = msg_content if response.message is None else response.message + "\n" + msg_content
            ## Convert the format of the citations into a ChatCitation
            if len(msg_citations) > 0: 
                if response.citations is None: 
                    response.citations = []
                for m_citation in msg_citations: 
                    response.citations.append(ChatCitation.from_data_source_citation(m_citation).to_api_response())
            
            ## Add the message to the history
            self._add_message_to_thread({ "content": msg_content, "role": 'assistant', "citations": response.citations })

        return more_steps

    def __process_finished_stream_chunk(self, choice:StreamChoice, response:ChatResponse) -> bool:
        more_steps = True
        ## We've got everything, so process it as normal...
        if choice.finish_reason == "tool_calls": 
            self.history.get('messages', []).append({
                "ts": int(time()*1000.0),   ## in millis
                "tool_calls": [{ "id":tool.id, "function":{ "arguments":tool.function.arguments, "name":tool.function.name }, "type":"function" } for tool in self._context.stream_chunk.tool_calls],
                "role": self._context.stream_chunk.role
            })
            self.__process_tool_calls(self._context.stream_chunk.tool_calls)
            self._context.stream_chunk.tool_calls = None
        elif choice.finish_reason == "content_filter":
            logging.warning(f"Finish Reason: Content Filtered, for Choice: {choice} [Doing Nothing with this for now]")
        elif choice.finish_reason == "function_call": 
            logging.warning(f"Finish Reason: Function Call, for Choice {choice} [Doing Nothing with this for now]")
        elif choice.finish_reason == "stop":
            if self._context.stream_chunk.accumulated_delta is not None and len(self._context.stream_chunk.accumulated_delta) > 0: 
                self._context.push_update_to_stream(StreamMessage({
                    "delta": self._context.stream_chunk.accumulated_delta
                }, INTERIM_RESULT))

            self.history.get('messages', []).append({
                "ts": int(time()*1000.0),   ## in millis
                "content": self._context.stream_chunk.content,
                "role": self._context.stream_chunk.role
            })
            response.message = self._context.stream_chunk.content if response.message is None else response.message + "\n" + self._context.stream_chunk.content
            more_steps = False
        elif choice.finish_reason == "length": 
            logging.warning(f"Finish Reason: Length, for Choice: {choice} [Doing Nothing with this for now]")
        return more_steps

    def __process_stream_chunk_from_data_extensions_api(self, choice:StreamChoice, response:ChatResponse) -> bool:
        messages = choice.model_extra.get('messages')
        end_turn, content_updated = self._context.stream_chunk.add_data_source_delta(messages)

        ## If the content was updated by this delta, then publish the interim result
        if content_updated:
            self._publish_interim_result()

        ## If it's the end of the turn, then we're done, publish any remaining updates, add the message to the history and return
        if end_turn: 
            ## If there are citations stored in the chunk, then add them to the response
            if self._context.stream_chunk.has_tool_citations():
                if response.citations is not None: 
                    response.citations.extend(self._context.stream_chunk.get_tool_citations())
                else: 
                    response.citations = self._context.stream_chunk.get_tool_citations()
            
            ## Publish any accumulated deltas
            self._publish_interim_result(True) ## Force publishing even if we only just recently published
            
            ## Add the Message to the History 
            self._add_message_to_thread({
                "content": self._context.stream_chunk.content,
                "role": self._context.stream_chunk.role, 
                "citations": [c.to_api_response() for c in response.citations]
            })
            ## And finally, add the message to the response
            response.message = self._context.stream_chunk.content if response.message is None else response.message + "\n" + self._context.stream_chunk.content
            return True
        else: 
            return False
        
    def __process_stream_chunk(self, choice:StreamChoice, response:ChatResponse) -> bool:
        ## Process the streaming choice response from the AI
        more_steps = True

        if choice.finish_reason is not None:
            more_steps = self.__process_finished_stream_chunk(choice, response)
        elif choice.delta is None:
            ## This is stream message from the Data Source Extensions API - add the delta to the chunk
            more_steps = self.__process_stream_chunk_from_data_extensions_api(choice, response)
        else:
            ## This is a delta message from the normal completion API
            self._context.stream_chunk.add_chunk_delta(choice.delta)
            self._publish_interim_result()
            
        return more_steps

    def __handle_stream_result(self, result:list[ChatCompletionChunk], response:ChatResponse) -> bool:
        more_steps = True 
        self._context.stream_chunk = ChunkData()
        for chunk in result:
            more_steps = self.__process_choices(chunk, response)
        return more_steps

    def __process_tool_calls(self, tool_calls:list[ChatCompletionMessageToolCall]):
        for tool in tool_calls:
            if tool.function is not None:
                result = self.__invoke_function_tool(tool.function.name, tool.function.arguments)
                self._add_message_to_thread({
                        "tool_call_id": tool.id,
                        "role": "tool",
                        "name": tool.function.name,
                        "content": result
                })

    def __invoke_function_tool(self, function_name, function_args) -> str:
        args = {} if function_args is None else json.loads(function_args)
        try:
            logging.debug(f"Invoking function: {function_name} with args: {args}")
            result = self._invoke_function_tool(function_name, **args)  

            ## Ensure response is a string
            r_type = type(result)
            if r_type is not str:
                if r_type is dict or r_type is list:
                    result = json.dumps(result, indent=4)
                elif r_type is bool:
                    result = "true" if result else "false"
                else: 
                    result = str(result)

        except Exception as e:
            logging.warning(f"Failed to invoke function with Error: {e}")
            result = "Failed"
        return result
    
    def __load_oai_data_source_config(self):
        self.completions_data_sources = None
        ds_config_name = self._context.get_data_source_config_name()
        if ds_config_name is None: return

        ## There is a data source configuration, so load it
        data_source_config = load_named_config(ds_config_name)

        ## If a data source configuration has been provided, then configure the proxy to use the OpenAI Data Source extensions API instead of the standard completions API
        if data_source_config is not None:
            self.completions_data_sources = data_source_config.get("data-sources", data_source_config) ## Assume data-sources are an array in a field
            if type(self.completions_data_sources) is not list: 
                self.completions_data_sources = [self.completions_data_sources]
                
            self.completions_adapter = CompletionsWithExtensionsAdapter(self._build_base_url(False), self._context.model, self.__get_version_for_datasource_completions(), self._context.api_key)            

    def __get_version_for_datasource_completions(self)->str:
        key = self._context.config.data_source_api_version if self._context.config is not None else None
        if key is None:
            key = os.environ.get('AZURE_OAI_DATA_SOURCES_API_VERSION', self._api_version)
        return key
