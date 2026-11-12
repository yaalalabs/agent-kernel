from agentkernel.aws import ECSIOHandler


def main():
    # The REST/IO service: the WebSocket $connect handshake validates its `?token=` query parameter
    # through the identity block in config.yaml (ECSIOHandler refuses to start WebSocket mode
    # without it), chat frames are enqueued, and the output-queue consumer pushes the reply chunks.
    ECSIOHandler.run()


if __name__ == "__main__":
    main()
