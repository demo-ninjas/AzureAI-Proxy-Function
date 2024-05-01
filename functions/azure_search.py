import os
from typing import Annotated

import tiktoken
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery

import utils

class _SourceVectorConfig:
    field:str
    dim:int
    knn:int

    def __init__(self, field:str = None, dim:int = 1024, knn:int = 5) -> None:
        self.field = field
        self.dim = dim
        self.knn = knn

class _SourceConfig: 
    service_endpoint:str
    index_name:str
    query_key:str
    embedding_model:str
    semantic_config:str
    vector_fields:list[_SourceVectorConfig]


## Setup Azure Search Client
ROOT_SERVICE_ENDPOINT = os.environ.get("AZURE_SEARCH_SERVICE_ENDPOINT", None)
ROOT_INDEX_NAME = os.environ.get("AZURE_SEARCH_INDEX_NAME", None)
ROOT_QUERY_KEY = os.environ.get("AZURE_SEARCH_QUERY_API_KEY", None)
ROOT_EMBEDDING_MODEL = os.environ.get("AZURE_SEARCH_EMBEDDING_LOOKUP_MODEL", "gpt-4")
ROOT_SEMANTIC_CONFIG = os.environ.get("AZURE_SEARCH_SEMANTIC_CONFIG", None)


ROOT_CONNECTION = None
CACHED_CONNECTIONS = {}


def __vector_field_parser(field:str) -> _SourceVectorConfig:
    config = _SourceVectorConfig()
    parts = field.split(":")
    config.field = parts[0].strip()
    config.dim = int(parts[1].strip()) if len(parts) > 1 else 1024
    config.knn = int(parts[2].strip()) if len(parts) > 2 else 3
    return config

VECTOR_FIELDS = [ __vector_field_parser(field) for field in os.environ.get("AZURE_SEARCH_VECTOR_FIELDS", "").split(",") ]
## VECTOR_FIELDS SPEC: "field_name:embedding_dim:knn,field_name:embedding_dim:knn"
## eg. "myembedding:1024:5,myotherembeddingfield:512:3"


def get_root_search_client() -> tuple[SearchClient, _SourceConfig]:
    global ROOT_CONNECTION
    if ROOT_CONNECTION is not None: return ROOT_CONNECTION

    if ROOT_SERVICE_ENDPOINT is None or ROOT_INDEX_NAME is None or ROOT_QUERY_KEY is None:
        raise ValueError("Azure Search environment variables not set - Please set the following environment variables: AZURE_SEARCH_SERVICE_ENDPOINT, AZURE_SEARCH_INDEX_NAME, AZURE_SEARCH_QUERY_API_KEY")

    config = _SourceConfig()
    config.service_endpoint = ROOT_SERVICE_ENDPOINT
    config.index_name = ROOT_INDEX_NAME
    config.query_key = ROOT_QUERY_KEY
    config.embedding_model = ROOT_EMBEDDING_MODEL
    config.semantic_config = ROOT_SEMANTIC_CONFIG
    config.vector_fields = VECTOR_FIELDS
    client = SearchClient(ROOT_SERVICE_ENDPOINT, ROOT_INDEX_NAME, AzureKeyCredential(ROOT_QUERY_KEY))
    ROOT_CONNECTION = (client, config)
    return ROOT_CONNECTION

def _get_source_config(source:str) -> _SourceConfig:
    config_item = utils.load_named_config(source)

    config = _SourceConfig()
    config.service_endpoint = config_item.get("endpoint", config_item.get("service-endpoint", None))
    config.index_name = config_item.get("index", config_item.get("index-name", None))
    config.query_key = config_item.get("query_api_key", config_item.get("query-key", None))
    config.embedding_model = config_item.get("embedding-model", "gpt-4")
    config.semantic_config = config_item.get("semantic-config", None)
    config.vector_fields = [ _SourceVectorConfig(field=field.get("field", field.get("name", None)), 
                                                    dim=field.get("dim", field.get("dimensions", 1024)), 
                                                    knn=field.get("knn", field.get("k-nearest-neighbors", 3))) 
                                for field in config_item.get("vector-fields", []) ]

    if config.service_endpoint is None or config.index_name is None or config.query_key is None:
        raise ValueError(f"Azure Search Source config '{source}' not configured properly")
    return config
    

def get_search_client(source:str = None) -> tuple[SearchClient, _SourceConfig]:
    global CACHED_CONNECTIONS

    if source is None: 
        return get_root_search_client()
    
    if source in CACHED_CONNECTIONS:
        return CACHED_CONNECTIONS[source]
    
    config = _get_source_config(source)
    client = SearchClient(config.service_endpoint, config.index_name, AzureKeyCredential(config.query_key))
    CACHED_CONNECTIONS[source] = (client, config)
    return CACHED_CONNECTIONS[source]
    
def create_embedding_encoder(embedding_model:str = None)->tiktoken.Encoding:
    return tiktoken.encoding_for_model(embedding_model if embedding_model is not None else ROOT_EMBEDDING_MODEL)

def search(
        query:Annotated[str, "The search criteria"], 
        complex_query:Annotated[bool, "When set to True, this will enable the criteria to be specified using 'Lucene' query format"] = False, 
        do_vector_search:Annotated[bool, "Whether or not to use vector search when searching"] = True, 
        match_all:Annotated[bool, "Whether or not to require all terms within the search to be matched"] = False,
        number_of_results:Annotated[int, "The number of relevant results to return"] = 10, 
        facets:Annotated[list[str]|None, "If facets are desired, specifies the list of facets to return with the search results"] = None, 
        use_semantic_ranking:Annotated[bool, "Whether or not to sort ther results using semantic ranking"] = True,
        source:Annotated[str|None, "The name of the source configuration to use for the search"] = None
        ) -> list:
    search_client,source_config = get_search_client(source)
    if not do_vector_search: 
        result = search_client.search(search_text=query, include_total_count=True, facets=facets, 
                                      query_type="full" if complex_query else "semantic" if source_config.semantic_config is not None and use_semantic_ranking is not None else "simple", 
                                      search_mode="all" if match_all else "any",
                                      semantic_configuration_name=source_config.semantic_config
                                      )
    else: 
        encoder = create_embedding_encoder(source_config.embedding_model)
        vec_tokens = encoder.encode(query)

        vec_queries = []
        for vec_config in source_config.vector_fields:
            q_tokens = vec_tokens + [0] * (int(vec_config.dim) - len(vec_tokens))
            vec_queries.append(VectorizedQuery(vector=q_tokens, fields=vec_config.field, k_nearest_neighbors=int(vec_config.knn or "3")))
        
        result = search_client.search(search_text=query, include_total_count=True, vector_queries=vec_queries, facets=facets, 
                                      query_type="full" if complex_query else "semantic" if source_config.semantic_config is not None and use_semantic_ranking is not None else "simple", 
                                      search_mode="all" if match_all else "any",
                                      semantic_configuration_name=source_config.semantic_config
                                      )
    
    out_list = []
    for _ in range(0, min(result.get_count(), number_of_results)):
        try: 
            doc = result.next()
            out_list.append(doc)
        except StopIteration:
            break

    if facets is not None:
        out = {
            "count": result.get_count(),
            "results": out_list,
            "facets": result.get_facets()
        }
    else: 
        out = {
            "count": result.get_count(),
            "results": out_list
        }

    return out

def get_document(id:Annotated[str, "The ID of the document to retrieve"],
                source:Annotated[str|None, "The name of the source configuration to use for the search"] = None) -> dict:
    search_client, _ = get_search_client(source)
    return search_client.get_document(id)

def lookup_document_by_field(field_name:Annotated[str, "The name of the field to search by"],
                             field_val:Annotated[str, "The value of the field to search for, aka. only return documents that have this exact value in the specified field"],
                             source:Annotated[str|None, "The name of the source configuration to use for the search"] = None) -> dict:
    return search(f"{field_name}:\"{field_val}\"", complex_query=True, match_all=True, number_of_results=1, use_semantic_ranking=False, do_vector_search=False, source=source)
