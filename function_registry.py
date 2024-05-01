import os
import logging
import inspect  
from inspect import Parameter

from openai.types.chat import ChatCompletionToolParam
from openai.types.shared_params import FunctionDefinition, FunctionParameters

from functions import *

from data import ChatFunctionConfig

class FunctionRegistry: 
    def __init__(self):
        self.functions = dict()
        self.base_functions_configs = []
        self.__load_base_functions()

    def register_base_function(self, name:str, description:str, func):
        if not callable(func):
            raise ValueError(f"Function {func} is not callable")
        self.functions[name] = (func, description)

        function_config = ChatFunctionConfig()
        function_config.name = name
        function_config.description = description
        function_config.function = getattr(func, '__name__', name)
        self.base_functions_configs.append(function_config)

    def generate_tools_definition(self, function_list:list[ChatFunctionConfig] = None) -> list[dict]:
        tools = []
        if function_list is None: 
            function_list = self.base_functions_configs

        for func_def in function_list:
            base_function, _ = self.functions.get(func_def.function, None)
            if base_function is None: 
                raise ValueError(f"Function {func_def.name} refers to base function {func_def.function} which is not a registered base function")

            logging.debug("Analysing Function: " + func_def.name)
            
            tool_param = ChatCompletionToolParam()
            tool_param['type'] = "function"
            tool_param['function'] = FunctionDefinition()
            tool_param['function']['name'] = func_def.name
            tool_param['function']['description'] = func_def.description
            tool_param['function']['parameters'] = {
                "type": "object",
                "properties": {},
                "required": []
            }

            props = tool_param['function']['parameters']['properties']
            req = tool_param['function']['parameters']['required']

            sig = inspect.signature(base_function)
            for param_name, param in sig.parameters.items():
                if func_def.args is not None and param_name in func_def.args: 
                    continue ## Skip any args that are pre-defined by the config

                if param_name == "self": continue
                if param_name == "context": continue
                if param_name == "metadata": continue

                clazz = param.annotation.__origin__ if hasattr(param.annotation, "__origin__") else param.annotation
                desc = param.annotation.__metadata__[0] if hasattr(param.annotation, "__metadata__") and len(param.annotation.__metadata__) > 0 \
                            else param.annotation.__doc__ if hasattr(param.annotation, "__doc__") \
                            else "The parameter " + param_name
                param_type = "string" if clazz  == str \
                                else "number" if clazz == int  \
                                else "object" if clazz == dict \
                                else "array" if clazz == list  \
                                else "boolean" if clazz == bool \
                                else "array" if "list" in str(param) \
                                else "object"
                props[param_name] = {
                    "type": param_type,
                    "description": desc
                }

                if param_type == "array":
                    if hasattr(clazz, "__args__") and len(clazz.__args__) > 0: ## For now, we're assuming the list type is the first type in the annotation and we're ignoring others
                        first_type_arg = str(clazz.__args__[0])
                        item_type_start = first_type_arg.index("[") + 1
                        first_type_item_type = first_type_arg[item_type_start : len(first_type_arg) - 1]
                        item_param_type = "string" if first_type_item_type  == "str" \
                                else "number" if first_type_item_type == "int"  \
                                else "object" if first_type_item_type.startswith("dict") \
                                else "array" if first_type_item_type.startswith("list")  \
                                else "boolean" if first_type_item_type == "bool" \
                                else "object"
                    else: 
                        item_param_type = "string"

                    props[param_name]["items"] = {
                        "type": item_param_type
                    }


                ## If no default value is provided, then the parameter is required
                if param.default == Parameter.empty:
                    req.append(param_name)

            tools.append(tool_param)

        return tools


    def __getitem__(self, name:str) -> any:
        (func, desc) = self.functions[name]
        return func

    def __contains__(self, name:str):
        return name in self.functions

    def __load_base_functions(self):
        self.register_base_function("search", "Function to search across a dataset. This includes the ability to perform a vector search across the vector fields. If you set complex_query to True, then you can use Lucene search syntax within your search", search)
        self.register_base_function("lookup_document_by_field", "Function to do field specific searches.", lookup_document_by_field)
        self.register_base_function("lookup_document", "Function to do field specific searches.", lookup_document_by_field)
        self.register_base_function("get_document", "Retrieve a document from the search index by its ID", get_document)
        self.register_base_function("get_item", "Retrieve a specific item from a Cosmos DB container", get_item)
        self.register_base_function("get_partition_items", "Get all the items within the specified partition from a Cosmos DB container", get_partition_items)
        self.register_base_function("upsert_item", "Update or insert an item tinto a Cosmos DB container", upsert_item)
        self.register_base_function("delete_item", "Delete an item from a Cosmos DB Container", delete_item)



GLOBAL_FUNCTIONS_REGISTRY = FunctionRegistry()