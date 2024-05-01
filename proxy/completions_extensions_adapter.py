import os
import requests
import openai
import httpx

class CompletionsWithExtensionsAdapter(requests.adapters.HTTPAdapter):
    def __init__(self, oai_base_url:str, model:str, api_version:str, api_key:str):
        self._url = f"{oai_base_url}/openai/deployments/{model}/extensions/chat/completions?api-version={api_version}"
        self._prefix = f"{oai_base_url}/openai/"
        self._client = openai.OpenAI(api_key=api_key, base_url=oai_base_url + "/openai")
        self._client._prepare_request = lambda request: self._prepare_request(request)

    def _prepare_request(self, request: httpx.Request):
        ## Update the URL to use the extensions endpoint
        if str(request.url).startswith(self._prefix):
            request.headers['api-key'] = self._client.api_key
            request.headers.pop('authorization')
            request.url = httpx.URL(self._url)
        return None
    
    def client(self) -> openai.OpenAI:
        return self._client