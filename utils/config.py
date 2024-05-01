import os
import json

from .fs import read_first_matching_file
from functions.cosmos_lookup import get_item

CACHED_CONFIGS = {}

def load_named_config(name:str) -> dict:
    """
    Loads a configuration with the specified name from one of the following locations: 
    * Environment variables
    * A file
    * The ROOT CosmosDB Configs Container
    """
    global CACHED_CONFIGS


    ## Check if the config is already loaded
    if name in CACHED_CONFIGS:
        return CACHED_CONFIGS[name]
    
    ## Load the config
    config_item = None

    ## Check if the config is specified in the environment variables
    config_str = os.environ.get(f"CONFIG_{name.upper()}", None)
    if config_str is not None:
        config_item = json.loads(config_str)
    
    ## Check if the config is specified in a file
    if config_item is None:
        config_str = read_first_matching_file(name, ["configs", "data-configs"], [".json", ".conf"])
        if config_str is not None:
            config_item = json.loads(config_str)

    ## Check if the config is specified in the ROOT Cosmos Container
    if config_item is None: 
        config_item = get_item("configs", name, "_CONFIGS_")
    
    ## If config is not found, raise an error
    if config_item is None:
        raise ValueError(f"The Configuration with name '{name}' was not found")
    
    ## Cache the config
    CACHED_CONFIGS[name] = config_item
    
    return config_item