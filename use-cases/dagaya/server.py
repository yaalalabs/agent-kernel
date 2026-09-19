import os
from dotenv import load_dotenv

load_dotenv()

# Disable tracing and telemetry to prevent 401 errors
os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["LITELLM_LOG"] = "ERROR"

# Force AgentKernel to use whatsapp config and load env vars before any agentkernel imports
os.environ["AK_CONFIG_PATH_OVERRIDE"] = "config-whatsapp.yaml"
if os.getenv("WHATSAPP_VERIFY_TOKEN"):
    os.environ["AK_WHATSAPP__VERIFY_TOKEN"] = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
if os.getenv("WHATSAPP_ACCESS_TOKEN"):
    os.environ["AK_WHATSAPP__ACCESS_TOKEN"] = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
if os.getenv("WHATSAPP_PHONE_NUMBER_ID"):
    os.environ["AK_WHATSAPP__PHONE_NUMBER_ID"] = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")

from agentkernel.core.config import AKConfig
AKConfig._reset()

from agentkernel.openai import OpenAIModule
from agent import AGENTS

def setup_free_llm():
    if "OPENAI_API_KEY" in os.environ and "OPENAI_BASE_URL" not in os.environ:
        return

    import litellm
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
        except Exception:
            return False

    providers = [
        {
            "name": "Google Gemini",
            "env_key": "GEMINI_API_KEY",
            "models": [
                "gemini/gemini-3.5-flash-lite",
                "gemini/gemini-3.1-flash-lite",
                "gemini/gemini-2.5-flash-lite",
                "gemini/gemini-2-flash-lite",
                "gemini/gemini-3.7-flash",
                "gemini/gemini-3.6-flash",
                "gemini/gemini-3.5-flash",
                "gemini/gemini-3-flash",
                "gemini/gemini-2.5-flash",
                "gemini/gemini-2-flash",
            ],
        },
        {
            "name": "Groq",
            "env_key": "GROQ_API_KEY",
            "models": [
                "groq/llama3-70b-8192",
                "groq/llama3-8b-8192",
                "groq/mixtral-8x7b-32768",
            ],
        },
    ]

    def check_provider(provider):
        api_key = os.environ.get(provider["env_key"], "").strip()
        if not api_key:
            return []
            
        import concurrent.futures
        working_models = set()
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(provider["models"])) as executor:
            future_to_model = {executor.submit(is_valid, model, api_key): model for model in provider["models"]}
            for future in concurrent.futures.as_completed(future_to_model):
                if future.result():
                    working_models.add(future_to_model[future])
        
        working_models_ordered = []
        for model in provider["models"]:
            if model in working_models:
                full_model_name = f"litellm/{model}"
                working_models_ordered.append(full_model_name)
                
                if provider["env_key"] == "GROQ_API_KEY":
                    os.environ["GROQ_API_KEY"] = api_key
                elif provider["env_key"] == "GEMINI_API_KEY":
                    os.environ["GEMINI_API_KEY"] = api_key

        return working_models_ordered

    all_working_models = []
    for provider in providers:
        all_working_models.extend(check_provider(provider))
        
    if all_working_models:
        os.environ["OPENAI_DEFAULT_MODEL"] = all_working_models[0]
        os.environ["OPENAI_MODEL_NAME"] = all_working_models[0]
        os.environ["AK_FALLBACK_MODELS"] = ",".join(all_working_models)

setup_free_llm()

model_name = os.environ.get("OPENAI_MODEL_NAME")
if model_name:
    for agent in AGENTS:
        agent.model = model_name

# Register agents with Agent Kernel
OpenAIModule(AGENTS)

if __name__ == "__main__":
    from agentkernel.api import RESTAPI
    from agentkernel.integration.whatsapp import AgentWhatsAppRequestHandler
    from tools import check_guardrail
    
    class DagayaWhatsAppRequestHandler(AgentWhatsAppRequestHandler):
        async def _handle_message(self, message: dict, value: dict):
            # Extract text to run the guardrail before processing
            message_type = message.get("type")
            text = None
            if message_type == "text":
                text = message.get("text", {}).get("body")
            elif message_type == "interactive":
                interactive = message.get("interactive", {})
                if interactive.get("type") == "button_reply":
                    text = interactive.get("button_reply", {}).get("title")
                elif interactive.get("type") == "list_reply":
                    text = interactive.get("list_reply", {}).get("title")
            elif message_type == "image":
                text = message.get("image", {}).get("caption", "")
            elif message_type == "document":
                text = message.get("document", {}).get("caption", "")

            if text:
                blocked_reply = check_guardrail(text)
                if blocked_reply:
                    from_number = message.get("from")
                    message_id = message.get("id")
                    if from_number:
                        self._log.warning(f"Guardrail blocked message from {from_number}")
                        await self._send_message(from_number, blocked_reply, message_id)
                    return
            else:
                # Unsupported message type (audio, sticker, location, etc)
                from_number = message.get("from")
                message_id = message.get("id")
                if from_number:
                    await self._send_message(from_number, "Ado! I can only read text and images right now. Please type your message or send a photo! 😅", message_id)
                return

            # If safe, let the normal Agent Kernel handler process it
            await super()._handle_message(message, value)

    class FixedWhatsAppHandler(DagayaWhatsAppRequestHandler):
        async def _send_message(self, to_number: str, text: str, reply_to_message_id: str = None):
            import asyncio
            
            image_url = None
            # Programmatically inject mascot images at the absolute first line to guarantee they load
            # based on LLM's response content, since LLMs sometimes ignore URL formatting rules.
            if "ado" in text.lower() and "!" in text and "https://" not in text[:20]:
                image_url = "https://ulfheonar.com/assets/dagaya/dagaya_wave.jpg?v=1"
            elif ("?" in text) and ("think" in text.lower() or "why" in text.lower() or "how" in text.lower()) and "https://" not in text[:20]:
                image_url = "https://ulfheonar.com/assets/dagaya/dagaya_thinking.jpg?v=1"
            elif ("fact" in text.lower() or "mind-blowing" in text.lower()) and "https://" not in text[:20]:
                image_url = "https://ulfheonar.com/assets/dagaya/dagaya_curious.jpg?v=1"
            elif ("100%" in text or "3/3" in text or "excellent" in text.lower()) and "https://" not in text[:20]:
                image_url = "https://ulfheonar.com/assets/dagaya/dagaya_celebrate.jpg?v=1"
            elif ("0/3" in text or "1/3" in text or "don't worry" in text.lower()) and "https://" not in text[:20]:
                image_url = "https://ulfheonar.com/assets/dagaya/dagaya_encourage.jpg?v=1"
                
            # Also handle if the LLM *did* properly include the image URL at the start
            if not image_url and text.strip().startswith("http"):
                lines = text.strip().split("\n")
                image_url = lines[0].strip()
                text = "\n".join(lines[1:]).strip()

            if image_url:
                # Send the image first on its own
                await super()._send_message(to_number, image_url, reply_to_message_id)
                # Wait 1.5 seconds so WhatsApp Cloud API finishes processing the media 
                # before we send the text, ensuring perfect chronological delivery!
                await asyncio.sleep(1.5)
                # Send the rest of the text without replying to the same message again
                if text.strip():
                    await super()._send_message(to_number, text.strip(), None)
            else:
                # Just send text normally
                await super()._send_message(to_number, text, reply_to_message_id)

    print("Starting Dagaya WhatsApp Webhook Server...")
    RESTAPI.run(handlers=[FixedWhatsAppHandler()])
