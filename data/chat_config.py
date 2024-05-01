import os
from utils import load_named_config

class ChatFunctionConfig: 
    name:str
    function:str
    description:str
    args:dict[str, any] = None

class ChatConfig:
    name:str

    oai_key:str = None
    oai_endpoint:str = None
    oai_region:str = None
    oai_version:str = None
    oai_model:str = None

    system_prompt:str = None
    temperature:float = None
    top_p:float = None
    max_tokens:int = None
    
    timeout_secs:int = None

    max_steps:int = None
    max_history:int = None

    functions:list[ChatFunctionConfig] = None

    use_data_source_config:bool = False
    data_source_config:str = None
    data_source_api_version:str = None

    def load(name:str) -> 'ChatConfig':
        config_item = load_named_config(name)

        config = ChatConfig()
        config.name = config_item.get("name", name)
        
        ## Map the config keys to the attribute names
        config_keys = {
            "oai_key": (str, ["oai-key", "ai-key"]),
            "oai_endpoint": (str, ["oai-endpoint", "ai-endpoint"]),
            "oai_region": (str, ["oai-region", "ai-region"]),
            "oai_version": (str, ["oai-version", "ai-version"]),
            "oai_model": (str, ["oai-model", "ai-model"]),
            "system_prompt": (str, ["system-prompt", "ai-prompt"]),
            "timeout_secs": (int, ["timeout", "timeout-secs", "ai-timeout"]),
            "temperature": (float, ["temperature", "ai-temperature"]),
            "use_data_source_config": (bool, ["use-data-source-config", "use-data-source-extensions"]),
            "data_source_config": (str, ["data-source-config", "ai-source-config"]),
            "data_source_api_version": (str, ["data-source-oai-version", "ai-source-config-api-version"]),
            "max_steps": (int, ["max-steps", "ai-max-steps"]),
            "max_history": (int, ["max-history", "ai-max-history"]),
            "top_p": (float, ["top-p", "top_p"]),
            "max_tokens": (int, ["max-tokens", "max-tokens-generated"])
        }

        ## Load the config from the configured keys
        for config_attr, (attr_type, keys) in config_keys.items():
            for key in keys:
                val = config_item.get(key)
                if val is not None:
                    ## If the value is a reference to an environment variable, then replace it with the value of that env variable
                    if type(val) is str and val.startswith("${") and val.endswith("}"):
                        val = os.getenv(val[2:-1], None)

                    ## Convert the value to the correct type
                    if attr_type == int:
                        val = int(val)
                    elif attr_type == float:
                        val = float(val)
                    elif attr_type == bool:
                        val = bool(val)
                    else: 
                        val = str(val)

                    ## Set the value
                    setattr(config, config_attr, val)
                    break

        
        ## Load the Functions (if any are configured)
        functions_conf = config_item.get("functions") or config_item.get("ai-functions")
        if functions_conf is not None and len(functions_conf) > 0: 
            functions = []
            for func_conf in functions_conf:
                func = ChatFunctionConfig()
                func.name = func_conf.get("name")
                func.function = func_conf.get("function")
                func.description = func_conf.get("description")
                func.args = func_conf.get("args")
                functions.append(func)
            config.functions = functions

        return config
