import os
from time import sleep, time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging 

from data import ChatContext, ChatResponse, ChatCitation
from openai import AzureOpenAI
from openai.types.beta.assistant import Assistant
from openai.types.beta.threads import Message, Run
from openai.types.beta.threads.run_submit_tool_outputs_params import ToolOutput

from .abstract_proxy import AbstractProxy

class AssistantsProxy(AbstractProxy):
    ### This class is responsible for managing the interaction with the Azure OpenAI Assisstants API
    
    def __init__(self, context:ChatContext) -> None:
        super().__init__(context)
        self.active_tool_runs = dict()

    def _create_thread(self, metadata: dict[str, str] = None) -> str:
        return self._client.beta.threads.create(metadata=metadata).id
        
    def upsert_assistant(self, assistant:Assistant)->str:
        """
        Create or Update an assistant, returning the Assistant ID 
        """ 
        res_assistant = None
        if assistant.id is None or len(assistant.id) == 0: 
            ## If the Assistant ID is not set, then create a new assistant
            res_assistant = self._client.beta.assistants.create(
                    model=assistant.model, 
                    description=assistant.name,
                    name=assistant.name, 
                    instructions=assistant.instructions,
                    file_ids=assistant.file_ids, 
                    tools=assistant.tools,
                    metadata=assistant.metadata
                )
        else: 
            res_assistant = self._client.beta.assistants.update(
                    assistant_id=assistant.id,
                    model=assistant.model, 
                    description=assistant.name,
                    name=assistant.name, 
                    instructions=assistant.instructions,
                    file_ids=assistant.file_ids, 
                    tools=assistant.tools,
                    metadata=assistant.metadata
                )
        
        return res_assistant.id

    def list_assistants(self)->list[Assistant]:
        """
        List all available assistants
        """
        assistants = []
        res = self._client.beta.assistants.list(order="asc")
        if res.data:
            assistants.extend(res.data)
            while res.has_next_page():
                res = res.get_next_page()
                if res.data: assistants.extend(res.data)
        return assistants
    
    def upload_data_source(self, file_name:str, file_data:bytes)->str:
        """
        Upload a data file, returning the assigned ID
        """
        res = self._client.files.create(purpose='assistants', file=(file_name, file_data))
        return res.id

    def list_data_sources(self, purpose:str = 'assistants')->str:
        """
        List all available data files that can be used by Assistants
        """
        files = []
        res = self._client.files.list(purpose=purpose)
        if res.data: files.extend(res.data)
        if res.has_next_page():
            res = res.get_next_page()
            if res.data: files.extend(res.data)
        return files


    def get_data_source(self, file_id:str)->str:
        """
        Get the file contents of a specific data file
        """
        info = self._client.files.retrieve(file_id=file_id)  ## Retrieve the file name
        res = self._client.files.content(file_id=file_id)    ## Retrieve the file contents
        return info.filename, res.content

    def create_thread(self, update_ctx:bool = True, metadata:dict[str,str] = None)->str:
        """
        Creates a new Conversation thread, updates the chat context with this thread + returns the thread ID 
        """
        thread_id = self._create_thread(metadata=metadata)
        if update_ctx: self._context.thread_id = thread_id
        return thread_id
        

    def send_message(self, message:str, in_thread:str = None, timeout_secs:int = 5, metadata:dict[str,str] = None) -> ChatResponse:
        """
        Send a user message and return the message id
        """

        ## Use the provided thread or default to the context thread
        thread_id = self._determine_thread_id(override_thread=in_thread)

        ## Check that there's no active runs on the thread
        run_check_start = time()
        run_list = self.get_runs_on_thread(thread_id=thread_id, sort="desc", max_count=50)
        # Check if any run has a status of active
        while any([run.status in ["queued", "in_progress", "cancelling"] for run in run_list]):
            run_list = self.get_runs_on_thread(thread_id=thread_id, sort="desc", max_count=50)
            if time() - run_check_start < timeout_secs: 
                sleep(0.2)
            else: 
                raise TimeoutError("Timeout waiting for all active runs to complete/fail before sending a message")

        ## Send the message to the thread
        msg = self._client.beta.threads.messages.create(thread_id=thread_id, content=message, role="user", metadata=metadata)
        response = ChatResponse()
        response.id = msg.id
        response.thread_id = thread_id
        return response

    def list_messages(self, in_thread:str = None, count:int = 10, sort:str = "desc", filter_role:str = None) -> list[Message]:
        """
        List the most messages in the current thread (sorted by the sort param - default descending), returning only the messages matching the role filter (if provided)
        
        NB: Currently count + sort are not implemented, so they are ignored
        """
        ## Use the provided thread or default to the context thread
        thread_id = self._determine_thread_id(override_thread=in_thread)

        messages = []
        res = self._client.beta.threads.messages.list(thread_id=thread_id, order="desc", limit=count*2)
        while len(messages) < count and res.data:
            filtered_messages = [data for data in res.data if filter_role is None or data.role == filter_role]
            messages.extend(filtered_messages[:count - len(messages)])
            if len(messages) < count and res.has_next_page():
                res = res.get_next_page()
        
        return messages
    
    def run_assistant(self, assistant_id:str, in_thread:str = None, metadata:dict[str,str] = None) -> str:
        """
        Run the assistant, return the Run ID
        """
        ## Determine which thread to run the assistant against
        thread_id = self._determine_thread_id(override_thread=in_thread, for_assistant=assistant_id)
            
        ## Run the Assistant in the current thread
        run = self._client.beta.threads.runs.create(assistant_id=assistant_id, thread_id=thread_id, metadata=metadata)
        return run.id

    def get_run(self, in_thread:str, run_id:str) -> Run:
        """
        Return the details for the specified Run
        """
        run = self._client.beta.threads.runs.retrieve(thread_id=in_thread, run_id=run_id)
        return run
        
    def get_runs_on_thread(self, thread_id:str, max_count:int = 30, sort:str = "desc") -> list[Run]:
        """
        Return the details for all the runs on the specified thread
        """
        res = self._client.beta.threads.runs.list(thread_id=thread_id, order=sort, limit=max_count)
        runs = []
        while len(runs) < max_count and res.data:
            runs.extend(res.data)
            if len(runs) < max_count and res.has_next_page():
                res = res.get_next_page()
        return runs

    def await_run_complete_or_fail(self, in_thread:str, run_id:str, timeout_secs:int = 90) -> Run: 
        """
        Wait for the specified run to complete or fail, returning the final run details
        """
        expire_time = time() + timeout_secs
        while time() <= expire_time:
            run = self.get_run(in_thread, run_id)
            ##  `queued`, `in_progress`, `requires_action`, `cancelling`, `cancelled`, `failed`, `completed`, or `expired`.
            if run.status in ["completed", "failed", "cancelled", "expired"]:
                return run
            elif run.status == "requires_action":
                if not self._are_run_tools_active(run.id):
                    threading.Thread(target=self.__handle_run_actions, args=(run, in_thread), daemon=True).start()
            sleep(1)
        raise TimeoutError("Run did not complete within the specified timeout period")


    def __handle_run_actions(self, run:Run, thread_id:str):
        if self._are_run_tools_active(run.id):
            return # Don't continue if there's already an active tool run for this run
        
        ## Mark the Tool Run as being active
        self._set_active_tool_run(run.id)

        try: 
            ## Invoke each of the run actions and submit them back to the run when they're complete
            if run.required_action and run.required_action.type == "submit_tool_outputs":
                executor = ThreadPoolExecutor(max_workers = 10)
                call_futures = []
                for tool_call in run.required_action.submit_tool_outputs.tool_calls:
                    if tool_call.type == "function":
                        function_call = tool_call.function
                        call_futures.append(executor.submit(self.__invoke_function_tool, function_call.name, function_call.arguments, tool_call.id, thread_id, run.id))
                    elif tool_call.type == "code_interpreter":
                        ## Ignore, this tool doesn't require any action on our part!
                        pass
                
                ## Now wait for them to finish, and collect the results up as they complete
                call_results = [future.result() for future in as_completed(call_futures) if future.result() is not None]
                self._client.beta.threads.runs.submit_tool_outputs(thread_id=thread_id, run_id=run.id, tool_outputs=call_results)
        except Exception as e:
            logging.error(f"Error handling run actions: {e}")
        finally: 
            self._clear_active_tool_run(run.id)

    def __invoke_function_tool(self, function_name, function_args, call_id, thread_id, run_id) -> ToolOutput:
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
            logging.error(f"Failed to invoke function with Error: {e}")
            result = "Failed"
        return ToolOutput(output=result, tool_call_id=call_id)


    def _are_run_tools_active(self, run_id:str) -> bool: 
        return run_id in self.active_tool_runs
    
    def _set_active_tool_run(self, run_id:str):
        self.active_tool_runs[run_id] = True

    def _clear_active_tool_run(self, run_id:str):
        if run_id in self.active_tool_runs:
            del self.active_tool_runs[run_id]
