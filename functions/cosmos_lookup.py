import datetime
import os
import logging
import json

import azure.cosmos.cosmos_client as cosmos_client
from azure.cosmos import ContainerProxy

import utils

ROOT_HOST = os.environ.get('COSMOS_ACCOUNT_HOST', None)
ROOT_COSMOS_KEY = os.environ.get('COSMOS_KEY', None)
ROOT_DATABASE_ID = os.environ.get('COSMOS_DATABASE_ID', None)
ROOT_CHATS_CONTAINER_ID = os.environ.get('COSMOS_CONTAINER_CHATS', "chats")
ROOT_CONFIGS_CONTAINER_ID = os.environ.get('COSMOS_CONTAINER_CONFIGS', "configs")

ROOT_CHATS_CONTAINER_CONNECTION:ContainerProxy = None
ROOT_CONFIGS_CONTAINER_CONNECTION:ContainerProxy = None

CONTAINER_CONNECTIONS = {}

def get_root_chats_cosmos_container() -> ContainerProxy: 
    global ROOT_CHATS_CONTAINER_CONNECTION
    if ROOT_CHATS_CONTAINER_CONNECTION is None: 
        if ROOT_HOST is None or ROOT_COSMOS_KEY is None or ROOT_DATABASE_ID is None or ROOT_CHATS_CONTAINER_ID is None:
            raise ValueError("Azure CosmosDB environment variables not set - Please set the following environment variables: COSMOS_ACCOUNT_HOST, COSMOS_KEY, COSMOS_DATABASE_ID, COSMOS_CONTAINER_ID")
        client = cosmos_client.CosmosClient(ROOT_HOST, {'masterKey': ROOT_COSMOS_KEY}, user_agent="OAIChatProxy", user_agent_overwrite=True)
        db = client.get_database_client(ROOT_DATABASE_ID)
        ROOT_CHATS_CONTAINER_CONNECTION = db.get_container_client(ROOT_CHATS_CONTAINER_ID)
    return ROOT_CHATS_CONTAINER_CONNECTION

def get_root_configs_cosmos_container() -> ContainerProxy: 
    global ROOT_CONFIGS_CONTAINER_CONNECTION
    if ROOT_CONFIGS_CONTAINER_CONNECTION is None: 
        if ROOT_HOST is None or ROOT_COSMOS_KEY is None or ROOT_DATABASE_ID is None or ROOT_CONFIGS_CONTAINER_ID is None:
            raise ValueError("Azure CosmosDB environment variables not set - Please set the following environment variables: COSMOS_ACCOUNT_HOST, COSMOS_KEY, COSMOS_DATABASE_ID, COSMOS_CONTAINER_ID")
        client = cosmos_client.CosmosClient(ROOT_HOST, {'masterKey': ROOT_COSMOS_KEY}, user_agent="OAIChatProxy", user_agent_overwrite=True)
        db = client.get_database_client(ROOT_DATABASE_ID)
        ROOT_CONFIGS_CONTAINER_CONNECTION = db.get_container_client(ROOT_CONFIGS_CONTAINER_ID)
    return ROOT_CONFIGS_CONTAINER_CONNECTION

class _ContainerConfig:
    host:str
    key:str
    database_id:str
    container_id:str


def _lookup_container_config(source:str) -> _ContainerConfig:
    config_item = utils.load_named_config(source)

    config = _ContainerConfig()
    config.host = config_item.get("host", None)
    config.key = config_item.get("key", config_item.get("masterKey", None))
    config.database_id = config_item.get("database", config_item.get("databaseId", None))
    config.container_id = config_item.get("container", config_item.get("containerId", None))
    if config.host is None or config.key is None or config.database_id is None or config.container_id is None:
        raise ValueError(f"Container config '{source}' not configured properly")
    return config

def connect_to_cosmos_container(source:str = None) -> ContainerProxy:
    global CONTAINER_CONNECTIONS
    if source is None:
        return get_root_chats_cosmos_container()
    if source == "_CONFIGS_":
        return get_root_configs_cosmos_container()
    
    if source in CONTAINER_CONNECTIONS:
        return CONTAINER_CONNECTIONS[source]
    
    config = _lookup_container_config(source)
    client = cosmos_client.CosmosClient(config.host, {'masterKey': config.key}, user_agent="OAIChatProxy", user_agent_overwrite=True)
    db = client.get_database_client(config.database_id)
    connection = db.get_container_client(config.container_id)
    CONTAINER_CONNECTIONS[source] = connection
    connection


def get_item(item_id:str, partition_key:str, source:str = None):
    source = connect_to_cosmos_container(source)
    return source.read_item(item=item_id, partition_key=partition_key)

def get_partition_items(partition_key:str, source:str = None):
    source = connect_to_cosmos_container(source)
    return list(source.query_items(
        query="SELECT * FROM c WHERE c.partitionKey=@partition_key ORDER BY c._ts DESC",
        parameters=[
            { "name":"@partition_key", "value": partition_key }
        ]
    ))

def upsert_item(item:dict, source:str = None):
    source = connect_to_cosmos_container(source)
    source.upsert_item(body=item)
    
def delete_item(item_id:str, partition_key:str, source:str = None):
    source = connect_to_cosmos_container(source)
    source.delete_item(item=item_id, partition_key=partition_key)
