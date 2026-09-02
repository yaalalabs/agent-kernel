import os
import sys

from dotenv import load_dotenv

load_dotenv()

from agentkernel.cli import CLI
from agentkernel.openai import OpenAIModule

from agent import AGENTS

# We support fallbacks by letting the user define multiple keys/models.
# For simplicity, if OPENAI_API_KEY is not set but GEMINI_API_KEY or GROQ_API_KEY is,
# we configure the standard OpenAI SDK to point to them.
# litellm can also be used as a proxy if running complex fallbacks.

def setup_free_llm():
    if "OPENAI_API_KEY" in os.environ and "OPENAI_BASE_URL" not in os.environ:
        return

    import litellm
    # Suppress verbose litellm logs
    litellm.suppress_debug_info = True

    def is_valid(model, api_key):
        if not api_key:
            return False
        try:
            litellm.completion(
                model=model,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1,
                api_key=api_key,
                num_retries=0,
                timeout=5,
            )
            return True
        except Exception as e:
            # We silently ignore validation failures to avoid cluttering the console
            return False

    providers = [
        {
            "name": "Google Gemini",
            "env_key": "GEMINI_API_KEY",
            "models": [
                # Tier 1: Highest Rate Limits (Flash Lite Series - ~500 RPD)
                "gemini/gemini-3.5-flash-lite",
                "gemini/gemini-3.1-flash-lite",
                "gemini/gemini-2.5-flash-lite",
                "gemini/gemini-2-flash-lite",
                
                # Tier 2: Standard Flash Series (Fast, balanced chatting - ~20 RPD)
                "gemini/gemini-3.7-flash",
                "gemini/gemini-3.6-flash",
                "gemini/gemini-3.5-flash",
                "gemini/gemini-3-flash",
                "gemini/gemini-2.5-flash",
                "gemini/gemini-2-flash",
                
                # Tier 3: Legacy Flash & Experimental Omni
                "gemini/gemini-1.5-flash",
                "gemini/gemini-1.5-flash-8b",
                "gemini/gemini-omni-1.1-flash",
                "gemini/gemini-omni-flash",
                
                # Tier 4: Pro Models (Slower, but highest intelligence fallback)
                "gemini/gemini-3.1-pro",
                "gemini/gemini-2.5-pro",
                "gemini/gemini-1.5-pro",
                "gemini/gemini-pro",
            ],
        },
        {
            "name": "Groq",
            "env_key": "GROQ_API_KEY",
            "models": [
                # New 2026 Models
                "groq/qwen/qwen3.8-27b",
                "groq/qwen/qwen3.6-27b",
                "groq/openai/gpt-oss-120b",
                "groq/openai/gpt-oss-20b",
                "groq/allam-2-7b",
                "groq/compound",
                
                # Legacy Models
                "groq/llama-3.3-70b-versatile",
                "groq/llama-3.1-8b-instant",
                "groq/llama-3.1-70b-versatile",
                "groq/mixtral-8x7b-32768",
                "groq/gemma2-9b-it",
            ],
        },
    ]

    valid_models_list = []

    for provider in providers:
        api_key = os.environ.get(provider["env_key"], "").strip()
        if not api_key:
            continue

        print(f"Testing {provider['name']} API...")
        import concurrent.futures
        working_models = set()
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(provider["models"])) as executor:
            future_to_model = {executor.submit(is_valid, model, api_key): model for model in provider["models"]}
            for future in concurrent.futures.as_completed(future_to_model):
                if future.result():
                    working_models.add(future_to_model[future])
        
        for model in provider["models"]:
            if model in working_models:
                full_model_name = f"litellm/{model}"
                valid_models_list.append((provider["name"], provider["env_key"], api_key, full_model_name))
                
    if not valid_models_list:
        print("⚠️ No valid API keys found or APIs are down! Please check your .env file.")
        
    return valid_models_list


import asyncio
from agentkernel.core import AgentService

async def run_chat(valid_models_list):
    if not valid_models_list:
        return
        
    model_idx = 0
    
    def apply_model(idx):
        provider_name, env_key, api_key, full_model_name = valid_models_list[idx]
        print(f"✅ Using {provider_name} with model: {full_model_name}")
        os.environ["OPENAI_DEFAULT_MODEL"] = full_model_name
        os.environ["OPENAI_MODEL_NAME"] = full_model_name
        if env_key == "GROQ_API_KEY":
            os.environ["GROQ_API_KEY"] = api_key
        elif env_key == "GEMINI_API_KEY":
            os.environ["GEMINI_API_KEY"] = api_key
            
        for agent in AGENTS:
            agent.model = full_model_name
            
    # Apply the first model
    apply_model(model_idx)
    
    # Initialize the Agent Kernel module with our agents
    OpenAIModule(AGENTS)
    
    service = AgentService()
    service.select(name="dagaya_triage")
    
    def get_safe_desc(agent_wrapper):
        if hasattr(agent_wrapper, 'agent') and hasattr(agent_wrapper.agent, 'handoff_description') and agent_wrapper.agent.handoff_description:
            return agent_wrapper.agent.handoff_description
        elif agent_wrapper.name == "dagaya_triage":
            return "Specialist in routing your requests to the right tutor or quiz master."
        return "Ready to assist you."

    print("\n\033[92m[System]: Welcome to Dagaya, your curious and playful AI learning companion!\033[0m")
    print("\033[92m[System]: Type !help for commands, !list to see available agents, and !select to switch agents.\033[0m")
    print(f"\033[92m[System]: You are now talking to {service.agent.name}. {get_safe_desc(service.agent)}\033[0m\n")
    
    print("AgentKernel CLI (Dynamic Fallback Enabled). Type !quit to exit.")
    
    async def run_prompt_with_fallback(prompt_text):
        nonlocal model_idx
        while True:
            try:
                response = await service.run(prompt=prompt_text)
                print(f"\033[35m{response}\033[0m\n")
                break
            except Exception as e:
                error_msg = str(e).lower()
                if "429" in error_msg or "rate limit" in error_msg or "quota" in error_msg or "overloaded" in error_msg or "unavailable" in error_msg:
                    model_idx += 1
                    if model_idx >= len(valid_models_list):
                        print("❌ All fallback models exhausted or rate limited!")
                        break
                    
                    print(f"\n⚠️ Rate limit or overload hit! Automatically switching to the next fallback model...")
                    apply_model(model_idx)
                    print("Retrying your prompt seamlessly...\n")
                else:
                    print(f"Error: {e}")
                    break

    # Trigger initial onboarding automatically
    await run_prompt_with_fallback("System Event: User joined a new session. Please enthusiastically introduce yourself in true Dagaya style! Ask if they would like to share their name, age, country, and the major exam they are preparing for to get a personalized experience. Make sure they know it is totally optional and they can just say 'no thanks' to jump right in!")

    while True:
        try:
            name = service.agent.name if service.agent else "none"
            prompt = await CLI._ainput(f"({name}) >> ")
            if not prompt.strip():
                continue
                
            # --- Guardrail Check ---
            try:
                sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                from tools import check_guardrail
                blocked = check_guardrail(prompt)
                if blocked:
                    print(f"\n\033[93m[Guardrail Blocked]: {blocked}\033[0m\n")
                    continue
            except ImportError:
                pass
            # --- End Guardrail Check ---
                
            if prompt.startswith("!"):
                tokens = prompt.lower().split()
                command = tokens[0]
                if command in ["!h", "!help"]:
                    print("Commands: !help, !list, !load, !new, !clear, !select, !quit")
                elif command in ["!c", "!clear"]:
                    service.clear()
                elif command in ["!q", "!quit"]:
                    break
                elif command in ["!ls", "!list"]:
                    agents = list(service.runtime.agents().values())
                    if not agents:
                        print("No agents available.")
                    else:
                        print("Available agents:")
                        for ag in agents:
                            print(f"  {ag.name}")
                        print()
                elif command in ["!n", "!new"]:
                    service.new()
                    print("\n\033[92m[System]: Started a new session! Welcome to Dagaya, your AI learning companion!\033[0m")
                    print("\033[92m[System]: Type !help for commands, !list to see available agents, and !select to switch agents.\033[0m\n")
                    await run_prompt_with_fallback("System Event: User joined a new session. Please enthusiastically introduce yourself in true Dagaya style! Ask if they would like to share their name, age, country, and the major exam they are preparing for to get a personalized experience. Make sure they know it is totally optional and they can just say 'no thanks' to jump right in!")
                elif command in ["!ld", "!load"]:
                    if len(tokens) != 2:
                        print("Usage: !load <module_name>")
                        continue
                    session_id = service.session.id if service.session else None
                    service.load(name=tokens[1], session_id=session_id)
                elif command in ["!s", "!select"]:
                    if len(tokens) != 2:
                        print("Usage: !select <agent_name>")
                        continue
                    session_id = service.session.id if service.session else None
                    service.select(name=tokens[1], session_id=session_id)
                    if service.agent:
                        print(f"\n\033[92m[System]: You are now talking to {service.agent.name}.\033[0m")
                        print(f"\033[92m[System]: {get_safe_desc(service.agent)}\033[0m\n")
                else:
                    print("Unknown command. Type !help for available commands.")
                continue
                
            # Run prompt with retry logic
            await run_prompt_with_fallback(prompt)

        except (KeyboardInterrupt, EOFError):
            break
        except Exception as e:
            print(f"CLI Error: {e}")


if __name__ == "__main__":
    models = setup_free_llm()
    try:
        asyncio.run(run_chat(models))
    except asyncio.CancelledError:
        print()
