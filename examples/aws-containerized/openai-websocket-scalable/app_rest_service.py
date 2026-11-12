from agentkernel.aws import AWSWebsocketAPI, ECSIOHandler


# A custom route receives the frame's raw body and the connection's principal: the identity the
# $connect handshake authenticated through the identity provider in config.yaml.
@AWSWebsocketAPI.register("echo")  # Terraform: ws_routes = [{ route = "echo" }]
async def echo(ctx: dict) -> dict:
    return {"message": ctx["message"], "principal": ctx["principal"].model_dump(mode="json", exclude_none=True)}


def main():
    # The REST/IO service: $connect authenticates through the identity block in config.yaml
    # (ECSIOHandler refuses to start WebSocket mode without it), chat frames are enqueued, and
    # the output-queue consumer pushes the replies.
    ECSIOHandler.run()


if __name__ == "__main__":
    main()
