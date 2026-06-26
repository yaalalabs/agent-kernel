from agentkernel.deployment.aws.containerized import ECSIOHandler

runner = ECSIOHandler.run

if __name__ == "__main__":
    runner()
