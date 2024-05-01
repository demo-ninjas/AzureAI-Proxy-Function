from concurrent.futures import ThreadPoolExecutor, as_completed
from time import sleep, time
import logging

from data import ChatContext, ChatResponse, ChatCitation
from proxy import AssistantsProxy

from openai.types.beta.assistant import Assistant
from openai.types.beta.threads import Message

ASSISTANT_REGISTRY = dict()

class AssistantProcessor:
    ### This class is responsible for managing the interaction with the Azure OpenAI Assistants
    
    context:ChatContext

    def __init__(self, context:ChatContext, assistants:list[str | dict[str,str]]) -> None:
        global ASSISTANT_REGISTRY
        self.context = context
        self.assistants = assistants
        self.assistant_lookup = ASSISTANT_REGISTRY
        self.proxy = AssistantsProxy(context)

    def process_prompt(self, prompt:str, timeout_secs:int = 90, metadata:dict = None) -> tuple[list[ChatResponse], int, int]: 
        if len(self.assistants) == 1:
            ## Single Assistant Prompt Processing
            assistant = self.assistants[0]
            assistant_id = self.__lookup_assistant(assistant).id
            
            ## Ensure Thread Exists
            if not self.context.has_thread():
                self.context.thread_id = self.proxy.create_thread(False)
            
            ## Process the Prompt in the thread
            success, messages = self.__process_prompt_in_thread(prompt, assistant_id, self.context.thread_id, timeout_secs, metadata)
            return self.__messages_to_response(messages), 1 if success else 0, 0 if success else 1 
        else: 
            ## Multi-assistant Prompt Processing
            return self.__orchestrate_prompt_with_assistants(prompt, timeout_secs)            
            
    
    def __messages_to_response(self, messages:list[Message]) -> list[ChatResponse]:
        chat_responses = []
        for assistant_msg in messages:
            resp = ChatResponse()
            resp.assistant_id = assistant_msg.assistant_id
            resp.id = assistant_msg.id
            resp.thread_id = assistant_msg.thread_id
            resp.metadata = {}
            if assistant_msg.file_ids is not None and len(assistant_msg.file_ids) > 0:
                resp.metadata["file_ids"] = assistant_msg.file_ids
            for content in assistant_msg.content:
                if content.type == "text":
                    resp.message = content.text.value if resp.message is None else resp.message + "\n" + content.text
                    if content.text.annotations is not None and len(content.text.annotations) > 0: 
                        for annotation in content.text.annotations:
                            if annotation.type == "file_citation":
                                citation = ChatCitation()
                                citation.id = annotation.file_citation.file_id
                                citation.text = annotation.file_citation.quote
                                citation.start = annotation.start_index
                                citation.end = annotation.end_index
                                citation.replace_part = annotation.text
                                resp.citations = [citation] if resp.citations is None else resp.citations.append(citation)
                            elif annotation.type == "file_path":
                                citation = ChatCitation()
                                citation.id = annotation.file_path.file_id
                                citation.start = annotation.start_index
                                citation.end = annotation.end_index
                                citation.replace_part = annotation.text
                                resp.citations = [citation] if resp.citations is None else resp.citations.append(citation)
                            else: 
                                logging.warning(f"Unknown annotation type: {annotation.type}")
                elif content.type == "image":
                    resp.metadata["image"] = [ content.image_file.file_id ] if "image" not in resp.metadata else resp.metadata["image"].append(content.image_file.file_id)
            chat_responses.append(resp)
        return chat_responses


    def __orchestrate_prompt_with_assistants(self, prompt:str, timeout:int, metadata:dict = None) -> tuple[list[Message], int, int]:
        start_time = time()

        ## Step 1: Extract the final assistant - it's the interpretation assistant with the user
        interpretation_assistant = self.__lookup_assistant(self.assistants.pop())
        
        ## Step 2: Run the prompt against each assistant (in their own threads)
        worker_threads = []
        executor = ThreadPoolExecutor(max_workers = 5)
        for assistant in self.assistants:
            assistant_id = self.__lookup_assistant(assistant).id
            assistant_thread_id = self.context.get_linked_thread(assistant_id)
            if assistant_thread_id is None: 
                assistant_thread_id = self.proxy.create_thread(False)
                self.context.add_linked_thread(assistant_id, assistant_thread_id)
            
            assistant_future = executor.submit(self.__process_prompt_in_thread, prompt, assistant_id, assistant_thread_id, (timeout - (time() - start_time), metadata))
            worker_threads.append(assistant_future)

        ## Step 3: Wait for all the threads to complete
        results = [future.result() for future in as_completed(worker_threads)]
        success_count = sum(success for success, _ in results)
        failure_count = len(results) - success_count
        res = [messages for _, messages in results if messages]
        
        ## Step 4: Process the final assistant
        ## Firstly, build a prompt for the final assistant based off the results of the other assistants
        final_prompt = self.__build_interpreter_prompt(res, prompt)
        if not self.context.has_thread():
            self.context.thread_id = self.proxy.create_thread()
        success, messages = self.__process_prompt_in_thread(final_prompt, interpretation_assistant.id, self.context.thread_id, max(20, (timeout - (time() - start_time)))) # Give the interpreter at least 20s to complete
        if success: success_count += 1
        else: failure_count += 1
        return self.__messages_to_response(messages), success_count, failure_count
              
            
    def __build_interpreter_prompt(self, res:list[list[Message]], trigger_prompt:str)->str: 
        prompt = "The following question has been posed:\n"
        prompt += trigger_prompt + "\n\n"
        prompt += "The  following responses have been provided by the other assistants:\n"
        for assistant_res in res:
            if len(assistant_res) == 0: continue

            try: assistant_name = self.__lookup_assistant(assistant_res[0].assistant_id).name
            except ValueError as e: assistant_name = assistant_res[0].assistant_id

            prompt += ">> Assistant: " + assistant_name + ":\n"
            for msg in assistant_res:
                for content in msg.content:
                    if content.type == "text":
                        prompt += f"{content.text }\n\t"
                    else: 
                        prompt += f"Image Response at path: {content.image_file.file_id }\n\t"
            prompt += "\n\n"
        prompt += "Please consider the responses from these assistants in relation to your understanding of the question and provide a suitable response to the question."
        prompt += "\nSome assistants may not have have the data or context needed to provide a suitable answer, or may not have understood the question. Please consider this in your response."
        return prompt


    def __process_prompt_in_thread(self, prompt:str, assistant:str, thread_id:str, timeout_secs:int, metadata:dict = None) -> tuple[bool, list[Message]]:
        start_time = time()
        expiry = start_time + timeout_secs
        try: 
            ## Step 1: Send the prompt to the thread
            self.proxy.send_message(prompt, thread_id, expiry - time())
            ## Step 2: Start a run for the assistant
            run_id = self.proxy.run_assistant(assistant, thread_id)
            ## Step 3: Wait for the run to complete
            run_result = self.proxy.await_run_complete_or_fail(thread_id, run_id, expiry - time())
        except TimeoutError as e: 
            logging.warning(f"[Assistant: {assistant}, Thread: {thread_id}] Timeout waiting for run '{run_id}' to complete")
            return False, None
        
        if run_result.status == "completed":
            res = []
            msgs = self.proxy.list_messages(in_thread=thread_id, filter_role="assistant", count=30, sort="desc")
            for msg in msgs:
                if msg.created_at is not None and msg.created_at > 0 and msg.created_at < start_time:
                    continue  # Skip any messages that are older than the prompt
                if msg.run_id is None or msg.run_id == run_id:
                    res.append(msg)
            return True, res
        else: 
            logging.warning(f"[Assistant: {assistant}, Thread: {thread_id}] Failed Run with result: {run_result.status}")
            return False, None

    def __lookup_assistant(self, assistant:str) -> Assistant: 
        ## Step 1: Check if the assistant is already in the lookup table
        matched = self.assistant_lookup.get(assistant.lower(), None)
        if matched is not None:
            return matched
        
        ## Step 2: If not, then load the current assistants list into the lookup table
        assistants = self.proxy.list_assistants()
        self.assistant_lookup.clear()
        for asst in assistants:
            self.assistant_lookup[asst.name.lower()] = asst
            self.assistant_lookup[asst.id.lower()] = asst

        ## Step 3: Check if the assistant is now in the lookup table
        matched = self.assistant_lookup.get(assistant.lower(), None)
        if matched is not None:
            return matched
        
        ## Step 4: If not, then raise an error
        raise ValueError(f"Assistant '{assistant}' not found")
