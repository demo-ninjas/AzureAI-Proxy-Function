import os

from azure.messaging.webpubsubservice import WebPubSubServiceClient
from azure.core.credentials import AzureKeyCredential

PUBSUB_CONNECTION:WebPubSubServiceClient = None

def _connect_to_pubsub() -> WebPubSubServiceClient:
    global PUBSUB_CONNECTION
    if PUBSUB_CONNECTION is None: 
        endpoint = os.environ.get('PUBSUB_ENDPOINT', None)
        if endpoint is None:
            raise ValueError("The PubSub endpoint is not set - Please set the following environment variable: PUBSUB_ENDPOINT")
        access_key = os.environ.get('PUBSUB_ACCESS_KEY', None)
        if access_key is None:
            raise ValueError("The PubSub access key is not set - Please set the following environment variable: PUBSUB_ACCESS_KEY")
        hub = os.environ.get("PUBSUB_HUB", "hub")

        PUBSUB_CONNECTION = WebPubSubServiceClient(endpoint=endpoint, hub=hub, credential=AzureKeyCredential(access_key))
    return PUBSUB_CONNECTION

def generate_access_url(stream_id:str, expire_mins:int = 90) -> str:
    service = _connect_to_pubsub()
    token = service.get_client_access_token(groups=[stream_id], roles=[f"webpubsub.joinLeaveGroup.{stream_id}"], minutes_to_expire=expire_mins)
    return token.get('url')

def push_message(stream_id:str, message:dict) -> None:
    service = _connect_to_pubsub()
    service.send_to_group(group=stream_id, message=message, content_type="application/json")
