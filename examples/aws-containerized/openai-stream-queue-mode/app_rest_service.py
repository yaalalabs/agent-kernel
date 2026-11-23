from agentkernel.aws import AWSWebsocketAPI


def main():
    # The REST/IO service: the WebSocket $connect handshake validates its `?token=` query parameter
    # through the identity block in config.yaml (AWSWebsocketAPI refuses to start
    # without it), chat frames are enqueued, and the output-queue consumer pushes the reply chunks.
    AWSWebsocketAPI.run()


if __name__ == "__main__":
    main()
