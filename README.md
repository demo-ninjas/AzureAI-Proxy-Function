## Azure OpenAI Chat Proxy Function
This is a prototype proxy Azure Function for interacting with the Azure OpenAI API.

It can be used as a starting point for building your own proxy function that adds your own semantics, RAG + callable function capabilities.


## API

There are 3 functions provided by this project:

* `/completion` - Chat with an AI model, using the completions API (supports streaming)
* `/assistant` - Chat with a pre-configured AI Assistant
* `/create-stream` - Get a Web PubSub stream to receive progress updates + interim results (currently, only the /completions function supports this)

### Chat with an AI Model

**Endpoint:** `/completion`

**Methods:**: `GET`, `POST`

Use this function to have an endless conversation conversation with an AI Model.
This function supports streaming interim results via an external Web PubSub stream.

All params can be specified in one of the following locations (within the request): 
* **Body Field** - A field within the POST body (the body must be a valid JSON document)
* **Header** - As a header
* **Query Parameter** - As a querystring parameter within the URL

*It is recommended to use the POST body (or headers) when sending any potentially sensitive data*

#### Params

* `prompt` - The message (prompt) from the user (type: `string`) [**REQUIRED**]
* `config` - The name of the configuration to use for this conversation (type: `string`)
* `context` - A value used by the function to link the request with an existing conversation (type: `string`)
* `stream-id` - The ID of the stream to publish progress updates + interim results to
* `prompt-file` - the name of the prompt file to use as the **system prompt** for this conversation (only used if the config doesn't contain a system prompt already)
* `openai-model-timeout` - The timeout (in seconds) for the request
* `openai-model-deployment` - The name of the Model deployment to use for this conversation
* `openai-region` - The region of the Azure OpenAI API to use
* `openai-model-temperature` - The temperature to apply for this chat interaction
* `openai-key` - The OpenAI Key to use for this chat

*Note: The defaults for the optional parameters can be configured via an external configuration, or via Environment Variables when deploying the Function App*

The `prompt` param is the only required parameter, however, the `context` param should be used for continuing a conversation after the initial interaction.

#### Response

The response from this endpoint will be a JSON document with the following fields: 

* `response` - The outcome of the chat interaction, with the following fields: 
  * `message` - The textual response from the AI
  * `citations` - An array of citations (if any)
  * `intent` - If calculated, the interpreted "intent" of the user's message
  * `id` - An unique ID assigned to the response message (if determined)
* `context` - An identifier for the conversation - this value shold be returned in subsequent requests for this conversation

Example Response: 
```json
{
    "response": {
        "message": "Sure, here is the answer to yor question."
    },
    "context": "abcdefhancafadacacnacsmacamcsdvhbdvmsdvdsavnbdmvbsdvjh="
}
```

The format of the `citations` is: 
* `id` - the ID of the citation (if known)
* `text` - a text snippet for the citation (if known)
* `url` - a url for the citation (if known)
* `title` - the title of the document/site of the citation (if known)
* `start` - the starting position within the document for the citation (if known)
* `end` - the end position within the document for the citation (if known)
* `replace_part` - the part of the response message that should be highig

#### Streaming Interim Results

When a `stream-id` is provided with the request, progress updates and interim results will be posted to the specified stream.

There are (currently) two types of messages published to the stream, identified by the `type` field: 

* `progress` - A plain english description of what the AI is currently doing (eg. "Analysing the data I've collected so far")
* `interim` - The next chunk of the textual response from the AI (concatenating all these together will produce the same message as the message contained within the API response)

You can use the `interim` messages to progressively build and display the response from the AI as it's generated out of the AI.

*Note: Before using a stream, you must use the `/create-stream` endpoint to create the stream and obtain a connection URL for the stream.*


### Chat with an AI Assistant

**Endpoint:** `/assistant`

**Methods:**: `GET`, `POST`

Use this function to have a conversation conversation with an AI Assistant.
AI assistants draw upon more in-built capabilities, such as writingn code, to answer user prompts.

All params can be specified in one of the following locations (within the request): 
* **Body Field** - A field within the POST body (the body must be a valid JSON document)
* **Header** - As a header
* **Query Parameter** - As a querystring parameter within the URL

*It is recommended to use the POST body (or headers) when sending any potentially sensitive data*

#### Params

* `prompt` - The message (prompt) from the user (type: `string`) [**REQUIRED**]
* `config` - The name of the configuration to use for this conversation (type: `string`)
* `context` - A value used by the function to link the request with an existing conversation (type: `string`)
* `assistant` - The name of the assistant to interact with (type: `string`)
* `assistants` - An array of assistants to request participation from for this conversation (type `[string]`) - before using this, check the **Multi-Assistant Mode** section below
* `openai-model-timeout` - The timeout (in seconds) for the request
* `openai-model-deployment` - The name of the Model deployment to use for this conversation
* `openai-region` - The region of the Azure OpenAI API to use
* `openai-key` - The OpenAI Key to use for this chat

*Note: The defaults for the optional parameters can be configured via an external configuration, or via Environment Variables when deploying the Function App*

The `prompt` param is the only required parameter, however, you must also specify either the `assistant` or `assistants` param. The `context` param should also be used for continuing a conversation after the initial interaction.

#### Response

The response from this endpoint will be a JSON document with the following fields: 

* `response` - An array of responses from the assistant(s), with each item in the array containing the following fields: 
  * `message` - The textual response from the Assistant
  * `citations` - An array of citations (if any)
  * `intent` - If calculated, the interpreted "intent" of the user's message
  * `assistant-id` - The ID of the assistant that answered the queestion (when using the Assistants endpoint)
  * `id` - An unique ID assigned to the response message (if determined)
* `context` - An identifier for the conversation - this value shold be returned in subsequent requests for this conversation

Example Response: 
```json
{
    "response": [
        {
            "message": "Sure, here is the answer to yor question.", 
            "assistant-id": "asst_adsatUWgOZEWVB6qCOKVu6xYXs"
        }
    ],
    "context": "abcdefhancafadacacnacsmacamcsdvhbdvmsdvdsavnbdmvbsdvjh="
}
```

#### Multi-Assistant Mode

When using the `/assistant` endpoint you can request multiple different assistants to participate in responding to the user prompt.

To enable this, specify an array of the names of each of the assistants you wish to participate in the `assistants` parameter of the request.

When you use multiple assistants they each work to answer the question independently and provide their own answer (or non-answer) to the prompt.

Hence, you **must** specify a single "interpteting" assistant as the last assistant in the list - this assistant should take the answers from each of the other assistants and interpret the collective answers into a single cohesive answer.

The assistants orchestrator will collect up the answers from each assistant and pass themm to the final assistant in the list with a prompt that has been crafted to request that assistant to appropriately interpret the answers and provide a single cohesive response.

The recommendation is that the system prompt for the "interpreting" assistant should be relatively generic and designed to assume prompts will be requesting an interpretation of the combined answers from other assistants.


### Create Stream

**Endpoint:** `/create-stream`

**Methods:**: `GET`

Use this function to create a [Web PubSub stream](https://azure.microsoft.com/en-au/products/web-pubsub) that can be used to recieve progress updates and interim results from interactions with the `/completions` endpoint.

*There are **no** params for this endpoint*

#### Response

The response from this endpoint will be a JSON document with the following fields: 

* `stream-id` - The ID of the stream - pass to to the `/completion` endpoint to have updates posted to the stream
* `stream-url` - The URL to use to connect to the stream - this url provides access to read messages posted to the specified stream ID for 90 mins

*Note: The `stream-url` is valid only for the next **90 mins** - after 90 mins, call this method again to get a new stream and pass the new `stream-id` to subsequent calls to the `/completion` endpoint

Example Response: 
```json
{
    "stream-id": "abc8df31c8fc47bd8b39129c8a218917",
    "stream-url": "wss://pubsubname-pubsub.webpubsub.azure.com/client/hubs/hubname?access_token=eyabdefghijkl..."
}
```


## Configuration

Requests to the `/completion` and `/assistant` endpoints can specify a `config` to use for their conversation - this is the *name* of a configuration to use for the conversation.

The following logic is used to find the specified configuration: 

* Check if there is an *environment variable* with the name: `CONFIG_{name}` (which includes the full configuration JSON) [Not Recommended]
* Check if there is a *file* with the config name in the filesystem under the folder: `{cwd}/configs/` (with a suffix of either `.json` or `.conf`)
* Check if there is an *item* in the `configs` container of the `root` Cosmos database with a partition key that matches the specified name

The configuration should be a JSON document (or a structured Cosmos item) that contains one or more of the following fields: 
* `name` - The name of the configuration
* `oai-key` (or `ai-key`) - The Azure OpenAI API Key to use
* `oai-endpoint` (or `ai-endpoint`) - The Azure OpenAI API endpoint to use 
* `oai-region` (or `ai-region`) - The Region of the Azure OpenAI API
* `oai-version` (or `ai-version`) - The version of the Azure OpenAI API to use
* `oai-model` (or `ai-model`) - The name of the Model Deployment with Azure OpenAI to use 
* `system-prompt` (or `ai-prompt`) - The system prompt to use 
* `timeout` (or `ai-timeout` or `timeout-secs`) - The timeout (in seconds) for interactions with the Azure OpenAI API
* `temperature` (or `ai-temperature`) - The temperature to apply to interactions with the `completions` API
* `use-data-source-config` (or `use-data-source-extensions`) - Boolean flag indicating whether or not to pass a data source configuration to the `completions` API, enabling the use of the API's data source extensions
* `data-source-config` (or `ai-source-config`) - The name of the data-source configuration (found using the same logic as this config) that should be loaded and passes to the Azure OpenAI API 
* `data-source-oai-version` (or `ai-source-config-api-version`) - Enables specifying a different API version when using the data source extensions the version of the API to use (if not specified will fallback to the `oai-version`
* `functions` (or `ai-functions`) - An array of function configs (that describe the functions that can be used by the AI)

The function configs are defined by: 
* `name` - The name of the function
* `function` - The name of the underlying base function that this function is actually using (must be a registered base function within the `FunctionRegistry`)
* `description` - A plain text description of the function (which will be provided to the AI to describe the purpose of the function)
* `args` - A dictionary of arguments that should be hard-coded to the specified values (eg. Use this to set the `source` argument for the `search` base-function)

Example Configuration: 
```json
{
    "name": "my-config",
    "temperature": 0.4,
    "functions": [
        {
            "name": "search-products", 
            "description": "Searches the product database for products that match the given query",
            "function": "search", 
            "args": {
                "source": "product-database"
            }
        }
    ]
}
```

This config can be used by specifying the `config` parameter with a value of `my-config` in requests the `/completion` or `/assistant` endpoints.

eg. `curl -XPOST --data '{ "prompt":"What shampoo do you have?", "config":"my-config", "stream-id":"abc123sskfjzvssdsdkhsdvjh"  }' https://api-host/completion`


With this config, any interactions with the AI will include a description of the `search-products` function that the AI can use. 
When the AI requests using this function, the underlying base function called `search` will be called with the `source` argument set to `product-database` (along with any other arguments provided by the AI) 

### Configuring Base Defaults 
The following environment variables can be used to configure the base defaults for settings within the function app:  (some of these can be overriden by configs)

* **AZURE_OAI_API_KEY** - The API key for interacting with the Azure OpenAI API
* **AZURE_OAI_ENDPOINT** - The Azure OpenAI API Endpoint to use
* **AZURE_OAI_MODEL_DEPLOYMENT** - The AI model deployment to use
* **AZURE_OAI_API_VERSION** - The Azure OpenAI API Version to use
* **AZURE_OAI_DATA_SOURCES_API_VERSION** - The OpenAI API version to use when using the Completions data sources extension API (if not specified, defaults to `AZURE_OAI_API_VERSION`)
* **COSMOS_ACCOUNT_HOST** - The host of the CosmosDB to use (for recording chats + for retrieving configs) [REQUIRED]
* **COSMOS_KEY** - The CosmosDB MasterKey for the CosmosDB [REQUIRED]
* **COSMOS_DATABASE_ID** - The ID of the CosmosDB databasse that contains the following collections: "chats" and "configs" [REQUIRED]
* **PUBSUB_ENDPOINT** - The Endpoint for the Web PubSub that is used for sending interim results to [REQUIRED]
* **PUBSUB_ACCESS_KEY** - The API Key for accessing the Web PubSub streams [REQUIRED]


## Base Functions

The following base functions are currently available: 

* **AI Search**
  * `search` - Searches an Azure AI Search Index (can optionally use Vector search + semantic sorting)
  * `lookup_document` - Retrieves a document from an Azure AI Search Index using an exact match on a field
  * `get_document` - Retrieves a document from an Azure AI Search index by its Document ID
* **CosmosDB**
  * `get_item` - Retrieves an item from a CosmosDB collection
  * `get_partition_items` - Retrieves all the items within a specific partition of a CosmosDB Collection
  * `upsert_item` - Updates (or inserts) an item in a CosmosDB Collection
  * `delete_item` - Deletes an item from a CosmosDB collection


### AI Search

Each of the AI search functions have a `source` argument, which specifies the name of the configuration to use for connection to the search index.

The configuration is retrieved ussing the same logic as the [conversation configurations](#configuration), and should contain the following fields: 

* `name` - The name of the configuration
* `endpoint` - The endpoint for the AI search instance
* `index` - The name of the index to search within
* `query-key` - The API Key to use for accessing the search index
* `semantic-config` - The name of the semantic config to use for doing semantic sorting (if using semantic sorting)
* `embedding-model` - The embedding model used (tiktoken based) for any vector fields within the index (if there are vector fields)
* `vector-fields` - An array of vector field definitions, with the following fields: 
  * `field` - The name of the field
  * `dim` - The number of dimensions for the vector
  * `knn` - The number of nearest neighbours to apply


Example Config: 
```json
{
    "name": "product-database", 
    "endpoint": "https://myaisearchaueast.search.windows.net", 
    "index": "products", 
    "query-key": "abcsafkjsdfkjksajfbsdkkajhbWAzSeB7Stup", 
    "embedding-model": "gpt-4", 
    "semantic-config": "product-semantic-config", 
    "vector-fields": [
        {
            "field": "full-embedding",
            "dim": 2048,
            "knn": 5
        }, 
        {
            "field": "category-embedding",
            "dim": 512,
            "knn": 3
        }, 
        {
            "field": "description-embedding",
            "dim": 512,
            "knn": 3
        }
    ]
}
```

### CosmosDB

Each of the Cosmos DB functions have a `source` argument, which specifies the name of the configuration to use for connection to the search index.

The configuration is retrieved ussing the same logic as the [conversation configurations](#configuration), and should contain the following fields: 

* `name` - The name of the configuration
* `host` - The endpoint for the Cosmos DB
* `key` - The API Key to use for accessing the Cosmos DB
* `database` - The Database ID to connect to
* `container` - The Dataabase Container to connect to

Example configuration: 
```json
{
    "name": "mydb", 
    "host": "https://mycosmos.documents.azure.com:443",
    "key": "AKHSJAKFHGADJHAXJAXBSJVXSJVCGS", 
    "database": "mydb", 
    "container" "myitems"
}
```


## Roadmap

- [x] Completions API: Synchronous
- [x] Completions API: Streaming (via Web PubSub)
- [x] Completions API: Data Source Extensions
- [x] Assistants API: Synchronous
- [ ] Assistants API: Streaming (Not supported by Azure OpenAI yet)
- [ ] Semantic Kernel Support (for more complex orchestration)
- [ ] Local Tools (Functions)
    - [x] Azure AI Search
    - [x] Cosmos DB
    - [ ] SQL DB
    - [ ] Maths Operations
    - [ ] PubSub messaging
    - [ ] Callling out to other Azure Functions
    - [ ] Controlled HTTP Request (interacting with external APIs/systems)
    - [ ] Write + run code (in a Sandbox)



## License

Distributed under the MIT License. See `LICENSE.txt` for more information.
