import azure.functions as func
import logging

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

logging.getLogger("azure").setLevel(logging.ERROR) ## Only log the ERRORs from the azure libraries (some of which are otherwise quite verbose in their logging)

@app.route(route="completion", methods=["POST", "GET"])
def chat_completion(req: func.HttpRequest) -> func.HttpResponse:
    import json
    from proxy import CompletionsProxy
    from data import ChatContext

    context = ChatContext(req)
    comp = CompletionsProxy(context)

    prompt = context.get_req_val("prompt", None)
    if prompt is None: 
        raise ValueError("No prompt specified")
    
    resp = comp.send_message(prompt)
    return func.HttpResponse(
        body=json.dumps({
            "response": resp.to_api_response(), 
            "context": context.build_context()
        }, indent=4),
        status_code=200, 
        headers={
            "content-type": "application/json",
        }
    )


@app.route(route="assistant", methods=["POST", "GET"])
def chat_with_assistant(req: func.HttpRequest) -> func.HttpResponse:
    import json
    from proxy import AssistantProcessor
    from data import ChatContext

    context = ChatContext(req)

    prompt = context.get_req_val("prompt", None)
    if prompt is None: 
        raise ValueError("No prompt specified")
    
    assistants = context.get_req_val("assistant", context.get_req_val("assistants", None))
    if assistants is None:
        raise ValueError("No assistant(s) specified")
    elif type(assistants) is str:
        assistants = assistants.split(",")

    timeout = int(context.get_req_val("timeout", context.get_req_val("timeout_secs", "90")))

    processor = AssistantProcessor(context, assistants)
    result, _, _ = processor.process_prompt(prompt, timeout)
    chat_responses = [resp.to_api_response() for resp in result]

    return func.HttpResponse(
        body=json.dumps({
            "response": chat_responses, 
            "context": context.build_context()
        }, indent=4),
        status_code=200, 
        headers={
            "content-type": "application/json",
        }
    )


@app.route(route="create-stream", methods=["POST", "GET"])
def create_stream(req: func.HttpRequest) -> func.HttpResponse:
    import json
    from uuid import uuid4
    from pubsub import generate_access_url

    stream_id = uuid4().hex
    stream_url = generate_access_url(stream_id, 90)
    return func.HttpResponse(
        body=json.dumps({
            "stream-id": stream_id,
            "stream-url": stream_url
        }, indent=4),
        status_code=200, 
        headers={
            "content-type": "application/json",
        }
    )

