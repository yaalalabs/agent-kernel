from ak_aws import Lambda
from ak_openai import AgentModule

from agent import triage_agent, math_agent, history_agent

AgentModule([triage_agent, math_agent, history_agent])

lambda_handler = Lambda.handler
