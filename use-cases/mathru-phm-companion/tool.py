"""Agent Kernel tools for the Mathru PHM companion.

Empty in phase 1. The tools listed in SPEC.md (register_mother, get_mother_profile,
compute_antenatal_schedule, compute_immunization_schedule, next_appointment,
screen_danger_signs, escalate_to_phm, phm_caseload, search_guidance) are added here from
phase 2 onward as plain functions, bound to an agent with OpenAIToolBuilder.bind.

Mother records are persisted by this module using the standard library sqlite3, which is
tool-owned storage unrelated to the Agent Kernel session backend.
"""
