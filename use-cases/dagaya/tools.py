import json
import random
import re
import warnings
from typing import Any

warnings.filterwarnings("ignore", category=RuntimeWarning)

from agentkernel import ToolContext

# ---------------------------------------------------------------------------
# Content Guardrail — blocks inappropriate input before the LLM sees it
# ---------------------------------------------------------------------------
_BLOCKED_PATTERNS = re.compile(
    r"\b("
    # Violence / weapons
    r"kill|murder|shoot|stab|bomb|weapon|gun|knife|blood|gore|torture|rape|abuse"
    r"|suicide|self.harm|cut myself|hurt myself|die|wanna die|want to die"
    # Adult content
    r"|porn|sex|nude|naked|xxx|adult content|18\+"
    # Hate
    r"|racist|racism|nazi|nigger|faggot|hate speech"
    r")\b",
    re.IGNORECASE,
)

def check_guardrail(message: str) -> str | None:
    """
    Check if a message contains inappropriate content for a children's app.
    Returns a safe refusal string if blocked, or None if the message is fine.
    Call this BEFORE sending any message to the LLM.
    """
    if _BLOCKED_PATTERNS.search(message):
        return (
            "Ado! That's not the kind of thing we talk about here. "
            "Let's keep things fun and safe! "
            "Ask me something cool about science, math, or animals instead! 😊"
        )
    return None


def _get_student_profile_data() -> dict[str, Any]:
    try:
        cache = ToolContext.get().session.get_non_volatile_cache()
        profile = cache.get("student_profile", {})
        if isinstance(profile, dict):
            return profile
        return {}
    except RuntimeError:
        return {}


def _set_student_profile_data(profile: dict[str, Any]) -> None:
    try:
        cache = ToolContext.get().session.get_non_volatile_cache()
        cache.set("student_profile", profile)
    except RuntimeError:
        pass


def get_student_profile() -> str:
    """Read the student's profile, including their preferred language, topics studied, and past quiz scores."""
    profile = _get_student_profile_data()
    return json.dumps(profile, indent=2)


def set_preferred_language(language: str) -> str:
    """Set the student's preferred language (e.g., English, Sinhala, Tamil) for future interactions."""
    profile = _get_student_profile_data()
    profile["preferred_language"] = language
    _set_student_profile_data(profile)
    return f"Preferred language set to {language}."


def set_student_context(name: str = "", age: str = "", country: str = "", exam: str = "") -> str:
    """Save the student's name, age, country, and upcoming major exam context. This should be gathered during initial onboarding. All fields are optional."""
    profile = _get_student_profile_data()
    if name: profile["name"] = name
    profile["age"] = age
    profile["country"] = country
    profile["exam"] = exam
    _set_student_profile_data(profile)
    return "Student context saved successfully."


def update_student_progress(topic: str, score: int, max_score: int) -> str:
    """Update the student's learning progress with a new quiz score."""
    profile = _get_student_profile_data()
    history = profile.setdefault("quiz_history", {})
    topic_history = history.setdefault(topic, [])
    
    topic_history.append({"score": score, "max_score": max_score})
    
    # Calculate average
    total_score = sum(h["score"] for h in topic_history)
    total_max = sum(h["max_score"] for h in topic_history)
    
    avg_percentage = (total_score / total_max) * 100 if total_max > 0 else 0
    
    if avg_percentage < 60:
        profile.setdefault("weak_topics", []).append(topic)
        # Remove duplicates
        profile["weak_topics"] = list(set(profile["weak_topics"]))
    elif topic in profile.get("weak_topics", []):
        profile["weak_topics"].remove(topic)
        
    _set_student_profile_data(profile)
    return f"Progress updated for {topic}. Average score: {avg_percentage:.1f}%."


def generate_quiz_topic(topic: str, difficulty: str = "medium") -> str:
    """
    Generate a quiz topic outline for the agent to use. 
    The agent should use this to formulate actual questions in the student's preferred language.
    """
    topics = {
        "science": ["Photosynthesis", "Gravity", "States of Matter", "Solar System"],
        "math": ["Fractions", "Algebra Basics", "Geometry (Shapes)", "Percentages"],
        "english": ["Tenses", "Adjectives", "Punctuation", "Vocabulary"],
    }
    
    # If the topic is broad, pick a specific subtopic
    topic_lower = topic.lower()
    subtopic = topic
    for broad_topic, subtopics in topics.items():
        if broad_topic in topic_lower:
            subtopic = random.choice(subtopics)
            break
            
    return json.dumps({
        "topic": topic,
        "selected_subtopic": subtopic,
        "recommended_difficulty": difficulty,
        "instructions": "Generate 3 multiple choice questions based on the selected subtopic. Ensure they are fun, engaging, and in the student's preferred language."
    }, indent=2)


def get_curious_fact(topic: str) -> str:
    """Fetch a fun, curious fact about a topic to keep the child engaged."""
    facts = {
        "space": "One million Earths could fit inside the Sun!",
        "animals": "Octopuses have three hearts and blue blood.",
        "math": "The number 0 was invented in ancient India.",
        "science": "Water can boil and freeze at the exact same time! It's called the 'triple point'.",
        "history": "Cleopatra lived closer in time to the Moon landing than to the building of the Great Pyramid of Giza."
    }
    
    for key, fact in facts.items():
        if key in topic.lower():
            return fact
            
    return "Did you know that asking questions makes your brain grow stronger every day?"


def search_online(query: str) -> str:
    """Search the web for up-to-date information on a specific topic. Use this when you don't know the answer or need facts."""
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))
            if not results:
                return "No results found."
            
            output = []
            for r in results:
                output.append(f"Title: {r['title']}\nBody: {r['body']}")
            return "\n\n".join(output)
    except ImportError:
        return "Search tool is not installed. Please tell the user to run 'uv pip install duckduckgo-search'."
    except Exception as e:
        return f"Error searching the web: {str(e)}"


def search_images_online(query: str) -> str:
    """Search the web for images and pictures related to a specific topic. Use this when the user asks to see photos, pictures, diagrams, or images of something (e.g., 'show me a picture of a gorilla', 'diagram of heart'). Returns direct image links."""
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.images(query, max_results=10))
            if not results:
                return "No images found."
            
            output = []
            for r in results:
                img_url = r.get("image", r.get("thumbnail", ""))
                img_lower = img_url.lower()
                
                # Filter out Wikimedia/Wikipedia as WhatsApp often fails to preview them
                if not img_url or "wikimedia.org" in img_lower or "wikipedia.org" in img_lower:
                    continue
                    
                # Ensure it's a standard image format that WhatsApp supports natively
                if "?" in img_lower:
                    img_lower = img_lower.split("?")[0]
                    
                if img_lower.endswith((".jpg", ".jpeg", ".png")):
                    output.append(img_url)
                    
                if len(output) >= 2:
                    break
                    
            if not output:
                return "No compatible images found."
                
            return "Here is the direct image URL (put it at the ABSOLUTE FIRST LINE of your response):\n" + output[0]
    except Exception as e:
        return f"Error searching for images: {str(e)}"
