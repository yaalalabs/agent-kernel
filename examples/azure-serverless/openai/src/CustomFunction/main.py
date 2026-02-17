import json

from azure.functions import HttpRequest, HttpResponse


# The handler Azure Functions will call
def handler(req: HttpRequest) -> HttpResponse:
    try:
        try:
            body = req.get_json()
        except ValueError:
            body = {"message": "No JSON body provided"}

        # Collect some info about the request
        data = {
            "method": req.method,
            "url": req.url,
            "headers": dict(req.headers),
            "body": body,
            "message": "Hello from AgentFunctionSec!",
        }

        # Respond with JSON
        return HttpResponse(json.dumps(data), status_code=200, mimetype="application/json")

    except Exception as e:
        return HttpResponse(json.dumps({"error": str(e)}), status_code=500, mimetype="application/json")
